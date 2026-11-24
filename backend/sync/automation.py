"""The manager tools that act: best eleven, scouting list, deadline alerts, instant sales.

Runs next to the sync. Every few minutes it looks at the leagues of the users who switched something
on in their settings, and after every sync it refits the market value forecast and refreshes the
scouting lists. Everything a user's automation does is written to `AutomationEvent`, so it can be
checked on the "Automatik" page.

Only the lineup is changed on its own, and only when the user switched that on. Sales are always a
click of the user.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import threading
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Engine, func
from sqlmodel import Session, select

from api.context import MatchContext, load_context, match_day_of
from api.schemas import (
    AutomationEventOut,
    CheckOut,
    CoachOut,
    ExpectationOut,
    ForecastQualityOut,
    LeagueForecastOut,
    LineupApplyOut,
    MatchdayOut,
    RescueOut,
    ScoutRunOut,
    SellAdviceOut,
    SellOut,
    SquadPlayerOut,
)
from auth.accounts import Accounts
from core import analytics, coach
from core.config import Settings
from db.models import (
    AutomationEvent,
    AutoScout,
    Fixture,
    ForecastLog,
    League,
    Manager,
    MarketSeen,
    MarketValueHistory,
    MatchdayLineup,
    MatchdayRanking,
    Player,
    PlayerForm,
    SquadEntry,
    Team,
    UserAutomation,
    UserLeague,
    UserSession,
    utcnow,
)
from kickbase import KickbaseAuthError, KickbaseClient, KickbaseError
from kickbase import models as kb
from sync.learning import LearningService
from sync.learning import sell_ratio as learned_sell_ratio
from sync.odds import OddsService
from sync.push import PushService

log = logging.getLogger(__name__)

### Kickbase's answer to an undocumented request is kept this long in the event log
RAW_LIMIT = 1500
### A better eleven is only saved when it is expected to bring at least this many more points
MIN_GAIN = 1.0
### Push before the session of a user without the env account runs out
SESSION_WARNING = timedelta(days=2)
FLAG_THRESHOLD = 250_000


def _raw(value: Any) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(value)
    return text[:RAW_LIMIT]


def parse_lineup(raw: Any) -> tuple[str | None, list[str]]:
    """The formation and player ids of a saved lineup. Kickbase does not document this answer, so
    the usual key names are tried."""
    if not isinstance(raw, dict):
        return None, []
    formation = None
    for key in ("type", "lt", "t", "fm"):
        value = raw.get(key)
        if isinstance(value, str) and value.count("-") == 2:
            formation = value
            break
    players = None
    for key in ("lp", "players", "it", "pls"):
        if isinstance(raw.get(key), list):
            players = raw[key]
            break
    ids: list[str] = []
    for item in players or []:
        if isinstance(item, (str, int)):
            ids.append(str(item))
        elif isinstance(item, dict):
            pid = item.get("i") or item.get("pi") or item.get("id")
            if pid is not None:
                ids.append(str(pid))
    ids = list(dict.fromkeys(pid for pid in ids if pid and pid != "0"))
    # Some responses contain the entire squad. Never score it as a starting eleven.
    if len(ids) > 11:
        return None, []
    return formation, ids


def form_matches(performance: kb.PlayerPerformance, now: datetime) -> list[list[int | None]]:
    """`[matchday, points, minutes, role, market value day]` of the club's matches of this season that
    are over, newest first. Role: 5 starting eleven, 3 substitute, 4 bench, None unknown."""
    season = performance.seasons[-1] if performance.seasons else None
    result: list[list[int | None]] = []
    for match in season.matches if season else []:
        over = match.match_status == coach.MATCH_FINISHED or (
            match.kickoff is not None and match.kickoff + coach.MATCH_LENGTH < now
        )
        if not over or match.day is None:
            continue
        minutes = int("".join(ch for ch in (match.minutes or "") if ch.isdigit()) or 0)
        value_day = match_day_of(match.kickoff) if match.kickoff else None
        result.append([match.day, match.points or 0, minutes, match.status, value_day])
    result.sort(key=lambda m: -(m[0] or 0))
    return result


class AutomationService:
    def __init__(
        self, settings: Settings, engine: Engine, accounts: Accounts, push: PushService, odds: OddsService | None = None
    ):
        self.odds = odds
        self.learning = LearningService(settings, engine)
        self._last_market_watch: dict[str, datetime] = {}
        self.settings = settings
        self.engine = engine
        self.accounts = accounts
        self.push = push
        self.model = coach.ForecastModel()
        self._model_day: int | None = None
        self._forms_lock = threading.Lock()
        self._last_lineup_check: dict[tuple[str, str], datetime] = {}
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._task: asyncio.Task | None = None

    ### ==============================================================================================
    ### Lifecycle
    ### ==============================================================================================

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop(), name="automation")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _loop(self) -> None:
        with contextlib.suppress(Exception):
            await self.refresh_model()
        while True:
            try:
                await self.tick(utcnow())
            except Exception:
                log.exception("Automation round failed")
            await asyncio.sleep(self.settings.automation.interval_minutes * 60)

    def _lock(self, user_id: str, league_id: str) -> asyncio.Lock:
        return self._locks.setdefault((user_id, league_id), asyncio.Lock())

    ### ==============================================================================================
    ### Clients and settings
    ### ==============================================================================================

    def client_for_user(self, user_id: str) -> KickbaseClient | None:
        """The env account never expires. Everybody else is reached through their newest session."""
        if self.accounts.service is not None and self.accounts.service_user_id == user_id:
            return self.accounts.service
        now = utcnow()
        with Session(self.engine) as session:
            row = session.exec(
                select(UserSession)
                .where(
                    UserSession.user_id == user_id,
                    UserSession.expires_at > now,
                    UserSession.token_expires_at > now,
                )
                .order_by(UserSession.token_expires_at.desc())
            ).first()
        return self.accounts.client_for_session(row.id) if row else None

    def session_expiry(self, user_id: str) -> datetime | None:
        if self.accounts.service_user_id == user_id:
            return None
        with Session(self.engine) as session:
            return session.exec(
                select(func.max(UserSession.token_expires_at)).where(UserSession.user_id == user_id)
            ).first()

    def get_settings(self, user_id: str, league_id: str) -> UserAutomation:
        with Session(self.engine) as session:
            return session.get(UserAutomation, (user_id, league_id)) or UserAutomation(
                user_id=user_id, league_id=league_id
            )

    def save_settings(self, row: UserAutomation) -> UserAutomation:
        row.updated_at = utcnow()
        with Session(self.engine) as session:
            merged = session.merge(row)
            session.commit()
            session.refresh(merged)
            return merged

    def _enabled(self) -> list[UserAutomation]:
        with Session(self.engine) as session:
            return list(
                session.exec(
                    select(UserAutomation).where(
                        UserAutomation.auto_scout
                        | UserAutomation.auto_lineup
                        | UserAutomation.deadline_alerts
                        | UserAutomation.listing_alerts
                        | UserAutomation.sell_alerts
                    )
                )
            )

    def record(
        self,
        user_id: str,
        league_id: str,
        kind: str,
        message: str,
        *,
        ok: bool = True,
        key: str | None = None,
        details: dict | None = None,
    ) -> None:
        with Session(self.engine) as session:
            session.add(
                AutomationEvent(
                    user_id=user_id,
                    league_id=league_id,
                    kind=kind,
                    key=key,
                    ok=ok,
                    message=message,
                    details=details or {},
                )
            )
            session.commit()
        (log.info if ok else log.warning)("Automation %s for %s: %s", kind, user_id, message)

    def _has_key(self, key: str) -> bool:
        with Session(self.engine) as session:
            return session.exec(select(AutomationEvent.id).where(AutomationEvent.key == key)).first() is not None

    def events(self, user_id: str, league_id: str, limit: int = 100) -> list[AutomationEventOut]:
        with Session(self.engine) as session:
            rows = session.exec(
                select(AutomationEvent)
                .where(AutomationEvent.user_id == user_id, AutomationEvent.league_id == league_id)
                .order_by(AutomationEvent.at.desc())
                .limit(limit)
            ).all()
            return [AutomationEventOut.model_validate(row) for row in rows]

    ### ==============================================================================================
    ### Market value forecast
    ### ==============================================================================================

    def _fit_and_log(self) -> tuple[coach.ForecastModel, int | None]:
        with Session(self.engine) as session:
            histories = dict(session.exec(select(MarketValueHistory.player_id, MarketValueHistory.points)).all())
        matches = self._match_points()
        latest = max((points[-1][0] for points in histories.values() if points), default=None)
        model = coach.fit_forecast(histories, matches)
        if latest is None:
            return model, None
        with Session(self.engine) as session:
            ### The real change for forecasts whose day has come
            open_logs = session.exec(select(ForecastLog).where(ForecastLog.actual.is_(None))).all()
            for entry in open_logs:
                points = histories.get(entry.player_id) or []
                today = analytics.value_on_day(points, entry.day)
                before = analytics.value_on_day(points, entry.day - 1)
                if points and points[-1][0] >= entry.day and today is not None and before is not None:
                    entry.actual = today - before
                    session.add(entry)
            ### Today's forecast for the next update
            known = set(session.exec(select(ForecastLog.player_id).where(ForecastLog.day == latest + 1)).all())
            for player_id, points in histories.items():
                if player_id in known or not points or points[-1][0] != latest:
                    continue
                prediction = coach.forecast(points, model, horizon=1, matches=matches.get(player_id))
                if prediction:
                    session.add(ForecastLog(player_id=player_id, day=latest + 1, predicted=prediction.next_change))
            session.commit()
        return model, latest

    async def refresh_model(self, force: bool = False) -> None:
        """Refits the forecast after every market value update. Cheap enough to run after each sync."""
        with Session(self.engine) as session:
            latest = session.exec(select(func.max(League.market_values_updated_at))).first()
        day = analytics.market_value_day(latest) if latest else None
        if not force and day is not None and day == self._model_day:
            return
        model, _ = await asyncio.to_thread(self._fit_and_log)
        self.model = model
        self._model_day = day
        log.info(
            "Market value forecast %s (%d rows, error %s vs. %s naive)",
            "learned" if model.learned else "uses the default weights",
            model.rows,
            f"{model.error:.4f}" if model.error is not None else "-",
            f"{model.naive_error:.4f}" if model.naive_error is not None else "-",
        )

    def forecast_quality(self, threshold: int = FLAG_THRESHOLD) -> ForecastQualityOut:
        with Session(self.engine) as session:
            rows = session.exec(
                select(ForecastLog.predicted, ForecastLog.actual).where(ForecastLog.actual.is_not(None))
            ).all()
        checked = len(rows)
        hits = sum(1 for p, a in rows if (p > 0) == (a > 0)) if checked else 0
        flagged = [(p, a) for p, a in rows if p >= threshold]
        return ForecastQualityOut(
            weights=list(self.model.weights),
            features=list(coach.FEATURE_NAMES),
            learned=self.model.learned,
            training_rows=self.model.rows,
            error=self.model.error,
            naive_error=self.model.naive_error,
            checked=checked,
            direction_hits=hits / checked if checked else None,
            mean_abs_error=round(sum(abs(p - a) for p, a in rows) / checked) if checked else None,
            flag_precision=sum(1 for _, a in flagged if a >= threshold) / len(flagged) if flagged else None,
        )

    def _match_points(self) -> dict[str, list[tuple[int, int]]]:
        """`(market value day, points)` per player from the stored forms."""
        with Session(self.engine) as session:
            rows = session.exec(select(PlayerForm.player_id, PlayerForm.matches)).all()
        return {
            pid: [(int(m[4]), int(m[1])) for m in matches if len(m) > 4 and m[4] is not None]
            for pid, matches in rows
        }

    def _sell_ratio(self) -> float | None:
        with Session(self.engine) as session:
            return learned_sell_ratio(session)

    def _forecasts_for(self, player_ids: list[str], horizon: int) -> dict[str, coach.Forecast]:
        with Session(self.engine) as session:
            histories = session.exec(
                select(MarketValueHistory.player_id, MarketValueHistory.points).where(
                    MarketValueHistory.player_id.in_(player_ids)
                )
            ).all()
            forms = dict(
                session.exec(
                    select(PlayerForm.player_id, PlayerForm.matches).where(PlayerForm.player_id.in_(player_ids))
                ).all()
            )
        result = {}
        for player_id, points in histories:
            matches = [(int(m[4]), int(m[1])) for m in forms.get(player_id, []) if len(m) > 4 and m[4] is not None]
            prediction = coach.forecast(points or [], self.model, horizon, matches)
            if prediction:
                result[player_id] = prediction
        return result

    def _forecasts(self, horizon: int = 3) -> dict[str, coach.Forecast]:
        with Session(self.engine) as session:
            histories = session.exec(select(MarketValueHistory.player_id, MarketValueHistory.points)).all()
        matches = self._match_points()
        result = {}
        for player_id, points in histories:
            prediction = coach.forecast(points or [], self.model, horizon, matches.get(player_id))
            if prediction:
                result[player_id] = prediction
        return result

    ### ==============================================================================================
    ### Scouting list
    ### ==============================================================================================

    async def reconcile_scouting(self, league: League, user_id: str, client: KickbaseClient) -> ScoutRunOut:
        """Puts the players with a forecast at or above the user's threshold on the Kickbase scouting
        list and takes the app's own entries off again once they drop below. Entries the user made by
        hand are never touched."""
        setting = await asyncio.to_thread(self.get_settings, user_id, league.id)
        async with self._lock(user_id, league.id):
            forecasts, scouted, squad = await asyncio.gather(
                asyncio.to_thread(self._forecasts),
                client.scouted_players(league.id),
                client.manager_squad(league.id, user_id),
            )
            on_list = {p.id for p in scouted.players}
            owned = {p.id for p in squad.players}
            active = await asyncio.to_thread(self._active_players, league.competition_id)
            candidates = sorted(
                (
                    (pid, f.next_change)
                    for pid, f in forecasts.items()
                    if f.next_change >= setting.scout_threshold and pid in active and pid not in owned
                ),
                key=lambda item: -item[1],
            )
            flagged = [pid for pid, _ in candidates]
            wanted = set(flagged[: setting.scout_limit])
            auto = await asyncio.to_thread(self._auto_scouts, user_id, league.id)

            added, removed = [], []
            for pid, row in auto.items():
                if pid not in on_list and not row.dismissed and pid in wanted:
                    ### Taken off by hand while still above the threshold: leave it off
                    row.dismissed = True
                    await asyncio.to_thread(self._save_auto, row)
            for pid in flagged[: setting.scout_limit]:
                row = auto.get(pid)
                if pid in on_list or (row is not None and row.dismissed):
                    continue
                await client.add_scouted_player(league.id, pid)
                await asyncio.to_thread(self._save_auto, AutoScout(user_id=user_id, league_id=league.id, player_id=pid))
                added.append(pid)
            for pid, row in auto.items():
                if pid in wanted:
                    continue
                if pid in on_list and not row.dismissed:
                    await client.remove_scouted_player(league.id, pid)
                    removed.append(pid)
                await asyncio.to_thread(self._delete_auto, row)

        if added or removed:
            names = await asyncio.to_thread(self._names, added + removed)
            message = ", ".join(
                part
                for part in (
                    f"+ {', '.join(names[p] for p in added)}" if added else "",
                    f"− {', '.join(names[p] for p in removed)}" if removed else "",
                )
                if part
            )
            self.record(user_id, league.id, "scout", message, details={"added": added, "removed": removed})
            if added:
                await self.push.send(
                    user_id,
                    "Neue Transferziele",
                    f"Auf deine Scoutingliste: {', '.join(names[p] for p in added)}",
                    "/merkliste",
                    tag=f"scout-{league.id}",
                )
        return ScoutRunOut(added=added, removed=removed, flagged=flagged)

    def _active_players(self, competition_id: int) -> set[str]:
        with Session(self.engine) as session:
            team_ids = set(session.exec(select(Team.id).where(Team.competition_id == competition_id)).all())
            return {
                pid
                for pid, team_id in session.exec(select(Player.id, Player.team_id).where(Player.active)).all()
                if team_id in team_ids
            }

    def _auto_scouts(self, user_id: str, league_id: str) -> dict[str, AutoScout]:
        with Session(self.engine) as session:
            return {
                row.player_id: row
                for row in session.exec(
                    select(AutoScout).where(AutoScout.user_id == user_id, AutoScout.league_id == league_id)
                )
            }

    def _save_auto(self, row: AutoScout) -> None:
        with Session(self.engine) as session:
            session.merge(row)
            session.commit()

    def _delete_auto(self, row: AutoScout) -> None:
        with Session(self.engine) as session:
            found = session.get(AutoScout, (row.user_id, row.league_id, row.player_id))
            if found:
                session.delete(found)
                session.commit()

    def dismiss_scout(self, user_id: str, league_id: str, player_id: str) -> None:
        """The user took a player off by hand. If the app had put him there, he stays off."""
        with Session(self.engine) as session:
            row = session.get(AutoScout, (user_id, league_id, player_id))
            if row is not None:
                row.dismissed = True
                session.add(row)
                session.commit()

    def _names(self, player_ids: list[str]) -> dict[str, str]:
        with Session(self.engine) as session:
            rows = session.exec(select(Player).where(Player.id.in_(player_ids))).all()
        names = {p.id: p.last_name for p in rows}
        return {pid: names.get(pid, pid) for pid in player_ids}

    ### ==============================================================================================
    ### Form and expected points
    ### ==============================================================================================

    async def refresh_forms(
        self, client: KickbaseClient, competition_id: int, player_ids: list[str], force: bool = False
    ) -> None:
        max_age = timedelta(hours=self.settings.automation.form_max_age_hours)
        stale = (
            player_ids if force else await asyncio.to_thread(self._stale_forms, player_ids, utcnow() - max_age)
        )

        async def load(pid: str) -> tuple[str, list[list[int]]] | None:
            try:
                performance = await client.player_performance(competition_id, pid)
            except KickbaseAuthError:
                raise
            except KickbaseError as e:
                log.debug("No form for player %s: %s", pid, e)
                return None
            return pid, form_matches(performance, utcnow())

        results = [r for r in await asyncio.gather(*(load(pid) for pid in stale)) if r]
        if results:
            await asyncio.to_thread(self._store_forms, results)

    def _stale_forms(self, player_ids: list[str], cutoff: datetime) -> list[str]:
        with Session(self.engine) as session:
            fresh = set(
                session.exec(
                    select(PlayerForm.player_id).where(
                        PlayerForm.player_id.in_(player_ids), PlayerForm.synced_at >= cutoff
                    )
                ).all()
            )
        return [pid for pid in player_ids if pid not in fresh]

    def _store_forms(self, results: list[tuple[str, list[list[int]]]]) -> None:
        now = utcnow()
        with self._forms_lock, Session(self.engine) as session:
            for pid, matches in results:
                session.merge(PlayerForm(player_id=pid, matches=matches, synced_at=now))
            session.commit()

    def _context(self, league: League, player_ids: list[str] | None) -> tuple[MatchContext, dict[str, Player]]:
        with Session(self.engine) as session:
            context = load_context(session, league.competition_id, player_ids, utcnow())
            query = select(Player)
            if player_ids is not None:
                query = query.where(Player.id.in_(player_ids))
            players = {p.id: p for p in session.exec(query)}
        return context, players

    async def refresh_all_forms(self, league: League, client: KickbaseClient) -> int:
        """The match points of every player whose club played since his form was stored. Feeds the
        forecast and the expected points of players outside the own squad. Once per match, so a
        matchday costs about one request per player."""
        stale = await asyncio.to_thread(self._forms_behind, league.competition_id)
        if not stale:
            return 0
        await self.refresh_forms(client, league.competition_id, stale, force=True)
        return len(stale)

    async def backfill_lineups(self, league: League, client: KickbaseClient) -> int:
        """The elevens of matchdays that were stored before lineups were kept, one request per matchday."""
        missing = await asyncio.to_thread(self._days_without_lineups, league.id)
        for day in missing:
            try:
                ranking = await client.ranking(league.id, day)
            except KickbaseAuthError:
                raise
            except KickbaseError as e:
                log.info("No lineups of matchday %s: %s", day, e)
                continue
            await asyncio.to_thread(self._store_lineups, league.id, day, ranking)
        return len(missing)

    def _days_without_lineups(self, league_id: str) -> list[int]:
        with Session(self.engine) as session:
            ranked = set(session.exec(select(MatchdayRanking.day).where(MatchdayRanking.league_id == league_id)).all())
            stored = set(session.exec(select(MatchdayLineup.day).where(MatchdayLineup.league_id == league_id)).all())
        return sorted(ranked - stored)

    def _store_lineups(self, league_id: str, day: int, ranking: kb.Ranking) -> None:
        with Session(self.engine) as session:
            for user in ranking.users:
                session.merge(
                    MatchdayLineup(
                        league_id=league_id, day=day, manager_id=user.id, players=[pid for pid in user.lineup if pid]
                    )
                )
            session.commit()

    def _forms_behind(self, competition_id: int) -> list[str]:
        now = utcnow()
        with Session(self.engine) as session:
            last_match: dict[str, datetime] = {}
            for f in session.exec(
                select(Fixture).where(Fixture.competition_id == competition_id, Fixture.kickoff.is_not(None))
            ):
                assert f.kickoff is not None
                end = f.kickoff + coach.MATCH_LENGTH
                if end > now:
                    continue
                for team in (f.team1_id, f.team2_id):
                    if team and (team not in last_match or end > last_match[team]):
                        last_match[team] = end
            synced = dict(session.exec(select(PlayerForm.player_id, PlayerForm.synced_at)).all())
            team_ids = set(session.exec(select(Team.id).where(Team.competition_id == competition_id)).all())
            stale = []
            for pid, team_id in session.exec(select(Player.id, Player.team_id).where(Player.active)).all():
                if team_id not in team_ids:
                    continue
                last = last_match.get(team_id or "")
                stored = synced.get(pid)
                if stored is None or (last is not None and stored < last):
                    stale.append(pid)
        return stale

    ### ==============================================================================================
    ### The viewer's matchday
    ### ==============================================================================================

    async def coach_view(self, league: League, user_id: str, client: KickbaseClient) -> CoachOut:
        now = utcnow()
        squad, budget = await asyncio.gather(
            client.manager_squad(league.id, user_id), client.own_budget(league.id)
        )
        try:
            formation, saved = parse_lineup(await client.lineup(league.id))
        except KickbaseAuthError:
            raise
        except KickbaseError as e:
            log.info("The saved lineup could not be read, using the ranking: %s", e)
            formation, saved = None, []
        source = "kickbase"
        ranking = await client.ranking(league.id)
        if not saved:
            own = next((u for u in ranking.users if u.id == user_id), None)
            _, saved = parse_lineup({"lp": own.lineup if own else []})
            source = "ranking"
        ids = [p.id for p in squad.players]
        await self.refresh_forms(client, league.competition_id, ids)
        others = sorted({pid for u in ranking.users if u.id != user_id for pid in u.lineup if pid})
        context, stored = await asyncio.to_thread(self._context, league, [*ids, *others])
        fixtures = context.fixtures
        upcoming = context.upcoming
        live = coach.live_matchday(fixtures, now)

        expectations: dict[str, coach.Expectation] = {
            p.id: context.expectation(p.id, p.position, p.status, p.team_id, p.average_points) for p in squad.players
        }

        candidates = [
            coach.LineupCandidate(p.id, p.position, expectations[p.id].expected, p.market_value) for p in squad.players
        ]
        best = coach.best_eleven(candidates, keep=saved)
        saved_expected = round(sum(expectations[pid].expected for pid in saved if pid in expectations), 1)
        real_budget = budget.budget

        rescue = None
        ratio = await asyncio.to_thread(self._sell_ratio)
        if real_budget is not None and real_budget < 0:
            plan = coach.rescue_sales(
                real_budget,
                [
                    coach.SellCandidate(p.id, p.position, expectations[p.id].expected, int(p.market_value * (ratio or 1.0)))
                    for p in squad.players
                ],
            )
            rescue = RescueOut(**asdict(plan), expected_loss=plan.expected_loss)

        checks = self._checks(real_budget, saved, best, saved_expected, expectations, stored, squad, upcoming, live)
        if source == "ranking":
            checks.append(CheckOut(level="info", message="Aufstellung aus der Rangliste: Die aktuell gespeicherte Elf konnte nicht verlässlich gelesen werden."))
        await asyncio.to_thread(self._store_budget, user_id, league.id, real_budget)

        ### Sell before the value drops
        updates = coach.updates_until(upcoming.deadline if upcoming else None, now)
        forecasts = await asyncio.to_thread(self._forecasts_for, ids, max(updates, 1))
        advice = []
        for p in squad.players:
            f = forecasts.get(p.id)
            tip = coach.sell_advice(p.id, f.projection, updates, p.id in best.player_ids) if f else None
            if tip:
                advice.append(SellAdviceOut(player_id=p.id, reason=tip.reason, expected_drop=tip.expected_drop, in_best=tip.in_best))
        advice.sort(key=lambda a: a.expected_drop)

        ### What every manager's saved eleven is expected to score
        league_forecast = []
        for user in ranking.users:
            lineup = saved if user.id == user_id else [pid for pid in user.lineup if pid]
            total = 0.0
            unavailable = 0
            for pid in lineup:
                if pid in expectations:
                    e = expectations[pid]
                elif pid in stored:
                    sp = stored[pid]
                    e = context.expectation(pid, sp.position, sp.status, sp.team_id, sp.average_points)
                else:
                    continue
                total += e.expected
                unavailable += e.availability == 0
            league_forecast.append(
                LeagueForecastOut(
                    manager_id=user.id,
                    name=user.name,
                    image=user.image,
                    is_self=user.id == user_id,
                    expected=round(total, 1),
                    fielded=len(lineup),
                    unavailable=unavailable,
                )
            )
        league_forecast.sort(key=lambda m: -m.expected)

        return CoachOut(
            matchday=MatchdayOut(day=upcoming.day, first_kickoff=upcoming.first_kickoff, deadline=upcoming.deadline)
            if upcoming
            else None,
            live_day=live,
            lineup_open=coach.lineup_open(fixtures, now),
            budget=real_budget,
            squad=[
                SquadPlayerOut(
                    id=p.id,
                    first_name=stored[p.id].first_name if p.id in stored else None,
                    last_name=p.last_name,
                    team_id=p.team_id,
                    image=(stored[p.id].image if p.id in stored else None) or p.image,
                    position=p.position,
                    status=p.status,
                    status_text=stored[p.id].status_text if p.id in stored else None,
                    market_value=p.market_value,
                    average_points=p.average_points,
                    purchase_price=p.purchase_price,
                    expected=ExpectationOut(**{**asdict(expectations[p.id]), "reasons": list(expectations[p.id].reasons)}),
                    forecast=forecasts[p.id].next_change if p.id in forecasts else None,
                    in_lineup=p.id in saved,
                    in_best=p.id in best.player_ids,
                )
                for p in sorted(squad.players, key=lambda p: (p.position, -expectations[p.id].expected))
            ],
            saved_formation=formation,
            saved_lineup=saved,
            saved_expected=saved_expected,
            best_formation=best.formation,
            best_lineup=list(best.player_ids),
            best_expected=best.expected,
            rescue=rescue,
            checks=checks,
            lineup_source=source,
            sell_advice=advice,
            league_forecast=league_forecast,
            updates_to_matchday=updates,
            sell_ratio=ratio,
        )

    def _checks(self, budget, saved, best, saved_expected, expectations, stored, squad, upcoming, live) -> list[CheckOut]:
        checks: list[CheckOut] = []
        names = {p.id: p.last_name for p in squad.players}
        if budget is None:
            checks.append(CheckOut(level="warn", message="Budget unbekannt: Spieltagsbereitschaft nicht vollständig prüfbar."))
        if budget is not None and budget < 0:
            checks.append(CheckOut(level="error", message=f"Budget negativ: {budget / 1e6:.2f} Mio. € – bis zur Deadline ausgleichen."))
        fielded = [pid for pid in saved if pid in expectations]
        if len(fielded) < 11:
            checks.append(CheckOut(level="error", message=f"Nur {len(fielded)} von 11 Plätzen besetzt."))
        for pid in fielded:
            e = expectations[pid]
            if e.availability == 0:
                checks.append(
                    CheckOut(level="warn", message=f"{names.get(pid, pid)} in der Startelf: {', '.join(e.reasons) or 'fällt aus'}.")
                )
            elif e.availability < 1:
                checks.append(CheckOut(level="warn", message=f"{names.get(pid, pid)} ist {', '.join(e.reasons)}."))
        gain = best.expected - saved_expected
        if not best.same_players(saved) and gain >= MIN_GAIN:
            checks.append(CheckOut(level="warn", message=f"Die beste Elf bringt voraussichtlich +{gain:.0f} Punkte mehr."))
        if live is not None:
            checks.append(CheckOut(level="info", message=f"Spieltag {live} läuft – die Aufstellung ist gesperrt."))
        if not checks:
            checks.append(CheckOut(level="ok", message="Alles bereit für den Spieltag."))
        return checks

    def _store_budget(self, user_id: str, league_id: str, budget: int | None) -> None:
        if budget is None:
            return
        with Session(self.engine) as session:
            membership = session.get(UserLeague, (user_id, league_id))
            if membership is not None:
                membership.budget = budget
                membership.budget_updated_at = utcnow()
                session.add(membership)
                session.commit()

    ### ==============================================================================================
    ### Acting at Kickbase
    ### ==============================================================================================

    async def apply_lineup(
        self, league: League, user_id: str, client: KickbaseClient, view: CoachOut | None = None, reason: str = "manuell"
    ) -> LineupApplyOut:
        view = view or await self.coach_view(league, user_id, client)
        if not view.lineup_open:
            raise KickbaseError("Die Aufstellung ist gerade gesperrt, der Spieltag läuft.", 409)
        try:
            response = await client.set_lineup(league.id, view.best_formation, view.best_lineup)
        except KickbaseError as e:
            self.record(
                user_id,
                league.id,
                "lineup",
                f"Aufstellung nicht gespeichert: {e}",
                ok=False,
                details={"formation": view.best_formation, "players": view.best_lineup, "reason": reason},
            )
            raise
        try:
            _, now_saved = parse_lineup(await client.lineup(league.id))
        except KickbaseError:
            now_saved = []
        confirmed = set(now_saved) == set(view.best_lineup)
        self.record(
            user_id,
            league.id,
            "lineup",
            f"Beste Elf ({view.best_formation}, {view.best_expected:.0f} erw. Punkte) gespeichert"
            + ("" if confirmed else " – Kickbase meldet eine andere Aufstellung zurück"),
            ok=confirmed,
            details={
                "formation": view.best_formation,
                "players": view.best_lineup,
                "reason": reason,
                "response": _raw(response),
                "after": now_saved,
            },
        )
        return LineupApplyOut(
            formation=view.best_formation, player_ids=view.best_lineup, confirmed=confirmed, response=_raw(response)
        )

    async def sell(self, league: League, user_id: str, client: KickbaseClient, player_id: str) -> SellOut:
        """Sells a player of the user to Kickbase right away. Only ever on the user's click."""
        squad = await client.manager_squad(league.id, user_id)
        player = next((p for p in squad.players if p.id == player_id), None)
        if player is None:
            raise KickbaseError("Der Spieler ist nicht in deinem Kader.", 404)
        before = (await client.own_budget(league.id)).budget
        response = await client.sell_to_kickbase(league.id, player_id)
        after = (await client.own_budget(league.id)).budget
        received = after - before if after is not None and before is not None else None
        await asyncio.to_thread(self._store_budget, user_id, league.id, after)
        self.record(
            user_id,
            league.id,
            "sell",
            f"{player.last_name} sofort verkauft"
            + (f" für {received / 1e6:.2f} Mio. € (MW {player.market_value / 1e6:.2f} Mio.)" if received else ""),
            details={
                "player_id": player_id,
                "market_value": player.market_value,
                "received": received,
                "response": _raw(response),
            },
        )
        return SellOut(player_id=player_id, budget=after, response=_raw(response))

    ### ==============================================================================================
    ### Rounds
    ### ==============================================================================================

    async def watch_market(self, league_id: str, rows: list[UserAutomation], now: datetime) -> None:
        """Reports new listings that are transfer targets or bargains, and rivals who have to sell."""
        client = await asyncio.to_thread(self.accounts.client_for_league, league_id)
        if client is None:
            return
        with Session(self.engine) as session:
            league = session.get(League, league_id)
        if league is None:
            return
        market = await client.market(league_id)
        new, first_run = await asyncio.to_thread(self._diff_market, league_id, market)
        info = await asyncio.to_thread(self._market_info, league, [p.id for p in new])
        forecasts, balances, names, clubs, upcoming = info

        ### Rivals in the red shortly before the deadline have to sell, their players come cheap
        emergency = []
        if upcoming is not None and timedelta(0) < upcoming.deadline - now < timedelta(hours=24):
            emergency = [mid for mid, (balance, _) in balances.items() if balance < 0]

        for row in rows:
            lines = []
            if not first_run:
                for player in new:
                    seller = player.seller.id if player.seller else None
                    if seller == row.user_id or not clubs.can_buy(row.user_id, player.team_id):
                        continue
                    reasons = []
                    f = forecasts.get(player.id)
                    if f and f.next_change >= row.scout_threshold:
                        reasons.append(f"Prognose {f.next_change / 1e3:+.0f} Tsd.")
                    if seller and player.price and player.price < player.market_value:
                        reasons.append("unter Marktwert")
                    if seller and seller in emergency:
                        reasons.append(f"{names.get(seller, 'Verkäufer')} im Minus")
                    if reasons:
                        lines.append(f"{player.last_name}: {', '.join(reasons)}")
            if lines:
                await self.push.send(
                    row.user_id, "Neu auf dem Markt", "; ".join(lines[:4]), "/markt", tag=f"market-{league_id}"
                )
                self.record(row.user_id, league_id, "push", "Neu auf dem Markt: " + "; ".join(lines))
            for mid in emergency:
                if mid == row.user_id:
                    continue
                emergency_key = f"emergency:{league_id}:{row.user_id}:{mid}:{upcoming.day if upcoming else 0}"
                if self._has_key(emergency_key):
                    continue
                balance = balances[mid][0]
                await self.push.send(
                    row.user_id,
                    "Konkurrent muss verkaufen",
                    f"{names.get(mid, mid)} steht geschätzt bei {balance / 1e6:.1f} Mio. € und muss vor der Deadline verkaufen.",
                    "/konkurrenz",
                    tag=f"emergency-{league_id}-{mid}",
                )
                self.record(
                    row.user_id, league_id, "push", f"{names.get(mid, mid)} geschätzt im Minus", key=emergency_key
                )

    def _diff_market(self, league_id: str, market: kb.Market) -> tuple[list[kb.MarketPlayer], bool]:
        with Session(self.engine) as session:
            seen = {
                row.player_id: row for row in session.exec(select(MarketSeen).where(MarketSeen.league_id == league_id))
            }
            first_run = not seen
            new = []
            current = set()
            for player in market.players:
                seller = player.seller.id if player.seller else None
                current.add(player.id)
                row = seen.get(player.id)
                if row is None or row.seller_id != seller:
                    new.append(player)
                    session.merge(
                        MarketSeen(league_id=league_id, player_id=player.id, seller_id=seller, price=player.price)
                    )
            for pid, row in seen.items():
                if pid not in current:
                    session.delete(row)
            session.commit()
        return new, first_run

    def _market_info(self, league: League, player_ids: list[str]):
        from api.insights import Insights

        forecasts = self._forecasts_for(player_ids, 1) if player_ids else {}
        with Session(self.engine) as session:
            insights = Insights(session, league, None, self.model)
            balances = insights.balances()
            names = {m.id: m.name for m in session.exec(select(Manager).where(Manager.league_id == league.id))}
            clubs = coach.ClubCounts.build(
                (entry.manager_id, team_id)
                for entry, team_id in session.exec(
                    select(SquadEntry, Player.team_id)
                    .join(Player, Player.id == SquadEntry.player_id)
                    .where(SquadEntry.league_id == league.id)
                )
            )
            context = load_context(session, league.competition_id, [], utcnow())
        return forecasts, balances, names, clubs, context.upcoming

    async def after_sync(self, league_id: str) -> None:
        """Called by the sync service after a league was stored."""
        try:
            with Session(self.engine) as session:
                league = session.get(League, league_id)
                rows = session.exec(
                    select(UserAutomation).where(UserAutomation.league_id == league_id, UserAutomation.auto_scout)
                ).all()
            if league is None:
                return
            client = self.accounts.client_for_league(league_id)
            refreshed = 0
            if client is not None:
                try:
                    await self.backfill_lineups(league, client)
                    refreshed = await self.refresh_all_forms(league, client)
                    if self.odds is not None:
                        await self.odds.refresh(client, league.competition_id)
                except KickbaseError as e:
                    log.warning("Forms or odds of %s not refreshed: %s", league.name, e)
            await self.refresh_model(force=refreshed > 50)
            await asyncio.to_thread(self.learning.after_sync, league)
            ### Kickbase's own achievement counters of everybody who can be asked, to learn the rules
            for member in await asyncio.to_thread(self.accounts.member_clients, league_id):
                user = member.user
                if user is not None:
                    try:
                        await self.learning.snapshot_achievements(league, user.id, member)
                    except KickbaseError as e:
                        log.info("Achievements of %s not read: %s", user.id, e)
            if self.accounts.service is not None and self.accounts.service_user_id:
                try:
                    await self.learning.snapshot_achievements(league, self.accounts.service_user_id, self.accounts.service)
                except KickbaseError as e:
                    log.info("Achievements of the server account not read: %s", e)
            for row in rows:
                client = self.client_for_user(row.user_id)
                if client is None:
                    continue
                try:
                    await self.reconcile_scouting(league, row.user_id, client)
                except KickbaseError as e:
                    self.record(row.user_id, league_id, "scout", f"Scoutingliste nicht abgeglichen: {e}", ok=False)
        except Exception:
            log.exception("Automation after the sync of %s failed", league_id)

    async def tick(self, now: datetime) -> None:
        settings = await asyncio.to_thread(self._enabled)
        watch: dict[str, list[UserAutomation]] = {}
        for row in settings:
            if row.listing_alerts:
                watch.setdefault(row.league_id, []).append(row)
        for league_id, rows in watch.items():
            last = self._last_market_watch.get(league_id)
            if last is not None and now - last < timedelta(minutes=self.settings.automation.market_watch_minutes):
                continue
            self._last_market_watch[league_id] = now
            try:
                await self.watch_market(league_id, rows, now)
            except KickbaseError as e:
                log.warning("Market watch of %s failed: %s", league_id, e)
            except Exception:
                log.exception("Market watch of %s crashed", league_id)
        for row in settings:
            with Session(self.engine) as session:
                league = session.get(League, row.league_id)
            if league is None or league.synced_at is None:
                continue
            client = self.client_for_user(row.user_id)
            if client is None:
                continue
            try:
                await self._round(league, row, client, now)
            except KickbaseAuthError:
                await asyncio.to_thread(self.accounts.forget_client, client)
            except KickbaseError as e:
                log.warning("Automation for %s in %s: %s", row.user_id, league.name, e)
            except Exception:
                log.exception("Automation for %s in %s crashed", row.user_id, league.name)

    async def _round(self, league: League, row: UserAutomation, client: KickbaseClient, now: datetime) -> None:
        conf = self.settings.automation
        with Session(self.engine) as session:
            fixtures = [
                coach.FixtureInfo(f.day, f.kickoff, f.status, f.team1_id, f.team2_id)
                for f in session.exec(select(Fixture).where(Fixture.competition_id == league.competition_id))
            ]
        upcoming = coach.next_matchday(fixtures, now)
        if upcoming is None:
            return
        to_deadline = upcoming.deadline - now
        key = (row.user_id, league.id)

        ### Session running out: the automation stops then, so the user is told in time
        expiry = self.session_expiry(row.user_id)
        if expiry is not None and expiry - now < SESSION_WARNING:
            session_key = f"session:{row.user_id}:{expiry.date().isoformat()}"
            if not self._has_key(session_key):
                await self.push.send(
                    row.user_id,
                    "Bitte neu anmelden",
                    "Deine Kickbase-Sitzung läuft bald ab. Danach pausiert die Automatik.",
                    "/login",
                )
                self.record(row.user_id, league.id, "push", "Hinweis: Sitzung läuft bald ab", key=session_key)

        ### The best eleven, more often the closer the deadline
        if row.auto_lineup and coach.lineup_open(fixtures, now):
            every = (
                conf.lineup_check_minutes_close
                if to_deadline <= timedelta(hours=conf.close_hours)
                else conf.lineup_check_minutes
            )
            last = self._last_lineup_check.get(key)
            if last is None or now - last >= timedelta(minutes=every):
                self._last_lineup_check[key] = now
                async with self._lock(*key):
                    view = await self.coach_view(league, row.user_id, client)
                    gain = view.best_expected - view.saved_expected
                    if set(view.best_lineup) != set(view.saved_lineup) and (gain >= MIN_GAIN or len(view.saved_lineup) < 11):
                        try:
                            await self.apply_lineup(league, row.user_id, client, view, reason="automatisch")
                        except KickbaseError as e:
                            await self.push.send(
                                row.user_id, "Aufstellung fehlgeschlagen", f"Die beste Elf konnte nicht gespeichert werden: {e}", "/spieltag"
                            )

        ### Daily sell advice, before the market value update in the evening
        local = now.astimezone(analytics.MARKET_VALUE_TIMEZONE)
        if row.sell_alerts and local.hour == self.settings.automation.sell_advice_hour:
            sell_key = f"sell:{league.id}:{row.user_id}:{local.date().isoformat()}"
            if not self._has_key(sell_key):
                async with self._lock(*key):
                    view = await self.coach_view(league, row.user_id, client)
                names = {p.id: p.last_name for p in view.squad}
                tips = [f"{names.get(a.player_id, a.player_id)} ({a.expected_drop / 1e3:+.0f} Tsd.)" for a in view.sell_advice[:4]]
                if tips:
                    await self.push.send(
                        row.user_id,
                        "Verkaufen vor dem Update?",
                        "Fallen voraussichtlich bis zum Spieltag: " + ", ".join(tips),
                        "/spieltag",
                        tag=f"sell-{league.id}",
                    )
                self.record(
                    row.user_id,
                    league.id,
                    "push",
                    "Verkaufsempfehlung: " + (", ".join(tips) if tips else "nichts zu verkaufen"),
                    key=sell_key,
                )

        ### Deadline alerts: only the latest due stage is sent, the earlier ones count as done
        if row.deadline_alerts and to_deadline > timedelta(0):
            due = [m for m in sorted(conf.alert_minutes) if to_deadline <= timedelta(minutes=m)]
            if due:
                stage = due[0]
                alert_key = f"alert:{league.id}:{row.user_id}:{upcoming.day}:{stage}"
                if not self._has_key(alert_key):
                    async with self._lock(*key):
                        view = await self.coach_view(league, row.user_id, client)
                    problems = [c for c in view.checks if c.level in ("error", "warn")]
                    if problems:
                        body = " ".join(c.message for c in problems[:3])
                        if view.rescue and view.rescue.sales:
                            names = {p.id: p.last_name for p in view.squad}
                            body += " Vorschlag: " + ", ".join(names.get(pid, pid) for pid in view.rescue.sales) + " verkaufen."
                        await self.push.send(
                            row.user_id,
                            f"Spieltag {upcoming.day}: noch {stage} Min.",
                            body,
                            "/spieltag",
                            tag=f"deadline-{league.id}",
                        )
                    for m in sorted(conf.alert_minutes):
                        if m >= stage:
                            k = f"alert:{league.id}:{row.user_id}:{upcoming.day}:{m}"
                            if not self._has_key(k):
                                self.record(
                                    row.user_id,
                                    league.id,
                                    "alert",
                                    f"Deadline-Check {stage} Min.: "
                                    + ("; ".join(c.message for c in problems) if problems else "alles in Ordnung"),
                                    ok=not problems,
                                    key=k,
                                )
