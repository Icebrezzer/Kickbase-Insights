"""Collects what the app learns from and fits it. Runs after every sync (see sync.automation).

Learned values are kept in `ModelState`, so they survive restarts and every answer of the API reads
the same ones.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

from pydantic.alias_generators import to_camel
from sqlalchemy import Engine
from sqlmodel import Session, select

from api.context import load_context
from core import coach, learning
from core.config import Settings
from db.models import (
    AchievementSnapshot,
    AuctionLog,
    AutomationEvent,
    ExpectationLog,
    Fixture,
    League,
    MarketListing,
    MatchdayRanking,
    ModelState,
    Player,
    PlayerForm,
    Team,
    Transfer,
    utcnow,
)
from kickbase import KickbaseAuthError, KickbaseClient, KickbaseError

log = logging.getLogger(__name__)

FIT_EVERY = timedelta(hours=24)
### A transfer this long after a listing belongs to it
AUCTION_WINDOW = timedelta(days=4)


def load_state(session: Session, key: str) -> dict:
    row = session.get(ModelState, key)
    return dict(row.data) if row else {}


def expectation_weights(session: Session) -> coach.ExpectationWeights:
    data = load_state(session, "expectation")
    if not data:
        return coach.ExpectationWeights()
    return coach.ExpectationWeights(**{k: v for k, v in data.items() if k in coach.ExpectationWeights.__dataclass_fields__})


def bidder_model(session: Session) -> learning.BidderModel:
    data = load_state(session, "bidder")
    if not data.get("weights"):
        return learning.BidderModel(auctions=int(data.get("auctions", 0)))
    return learning.BidderModel(tuple(data["weights"]), float(data.get("bias", 0)), int(data.get("auctions", 0)))


def achievement_mode(session: Session) -> str:
    return str(load_state(session, "achievement_mode").get("mode", "matchday"))


def sell_ratio(session: Session) -> float | None:
    value = load_state(session, "sell_ratio").get("ratio")
    return float(value) if value else None


class LearningService:
    def __init__(self, settings: Settings, engine: Engine):
        self.settings = settings
        self.engine = engine

    def _save(self, key: str, data: dict) -> None:
        with Session(self.engine) as session:
            row = session.get(ModelState, key) or ModelState(key=key)
            row.data = data
            row.updated_at = utcnow()
            session.add(row)
            session.commit()

    def _due(self, key: str) -> bool:
        with Session(self.engine) as session:
            row = session.get(ModelState, key)
        return row is None or utcnow() - row.updated_at > FIT_EVERY

    ### ==============================================================================================
    ### A: expected points
    ### ==============================================================================================

    def log_expectations(self, league: League) -> int:
        """Stores what is expected of every active player for the next matchday, overwritten until
        it starts. The real points are filled in once the matchday is over."""
        now = utcnow()
        with Session(self.engine) as session:
            context = load_context(session, league.competition_id, None, now)
            if context.upcoming is None or now >= context.upcoming.deadline:
                return 0
            team_ids = set(session.exec(select(Team.id).where(Team.competition_id == league.competition_id)).all())
            players = [p for p in session.exec(select(Player).where(Player.active)) if p.team_id in team_ids]
            teams = max((v for v in context.placements.values() if v is not None), default=18)
            count = 0
            for p in players:
                fixture = context.fixture_of(p.team_id)
                if fixture is None:
                    continue
                e = context.expectation(p.id, p.position, p.status, p.team_id, p.average_points)
                row = session.get(ExpectationLog, (league.competition_id, context.day, p.id)) or ExpectationLog(
                    competition_id=league.competition_id, day=context.day, player_id=p.id
                )
                row.expected = e.expected
                row.form = e.form
                row.average = e.season_average
                row.chance = (e.play_probability if e.play_probability is not None else 1.0) * e.availability
                row.win = e.win_probability
                row.table = coach.table_term(context.placements.get(e.opponent_id or ""), max(teams, 2))
                row.home = e.home
                row.logged_at = now
                session.add(row)
                count += 1
            session.commit()
        return count

    def fill_actuals(self, competition_id: int) -> int:
        with Session(self.engine) as session:
            open_rows = session.exec(
                select(ExpectationLog).where(ExpectationLog.competition_id == competition_id, ExpectationLog.actual.is_(None))
            ).all()
            if not open_rows:
                return 0
            forms = dict(
                session.exec(
                    select(PlayerForm.player_id, PlayerForm.matches).where(
                        PlayerForm.player_id.in_(list({r.player_id for r in open_rows}))
                    )
                ).all()
            )
            filled = 0
            for row in open_rows:
                match = next((m for m in forms.get(row.player_id, []) if m and m[0] == row.day), None)
                if match is not None:
                    row.actual = int(match[1] or 0)
                    session.add(row)
                    filled += 1
            session.commit()
        return filled

    def fit_expectations(self, competition_id: int, force: bool = False) -> coach.ExpectationWeights | None:
        if not force and not self._due("expectation"):
            return None
        with Session(self.engine) as session:
            logged = [
                learning.ExpectationRow(r.form, r.average, r.chance, r.win, r.table, r.home, r.actual)
                for r in session.exec(
                    select(ExpectationLog).where(
                        ExpectationLog.competition_id == competition_id, ExpectationLog.actual.is_not(None)
                    )
                )
                if r.actual is not None
            ]
            ### Rebuilt from the season's matches, so there is something to learn from on day one
            placements = {
                t.id: t.placement for t in session.exec(select(Team).where(Team.competition_id == competition_id))
            }
            opponents: dict[str, dict[int, tuple[str | None, bool]]] = {}
            for f in session.exec(select(Fixture).where(Fixture.competition_id == competition_id)):
                if f.team1_id:
                    opponents.setdefault(f.team1_id, {})[f.day] = (f.team2_id, True)
                if f.team2_id:
                    opponents.setdefault(f.team2_id, {})[f.day] = (f.team1_id, False)
            teams_of = dict(session.exec(select(Player.id, Player.team_id)).all())
            history = []
            for pid, matches in session.exec(select(PlayerForm.player_id, PlayerForm.matches)).all():
                history.extend(learning.history_rows(matches, opponents.get(teams_of.get(pid) or "", {}), placements))
        weights = learning.fit_expectation(logged + history)
        self._save(
            "expectation",
            {
                "form": weights.form,
                "average": weights.average,
                "win": weights.win,
                "table": weights.table,
                "rows": weights.rows,
                "error": weights.error,
                "default_error": weights.default_error,
                "logged_rows": len(logged),
                "history_rows": len(history),
            },
        )
        log.info("Expected points weights %s (%d rows)", weights, len(logged) + len(history))
        return weights

    ### ==============================================================================================
    ### B: achievements and balances
    ### ==============================================================================================

    async def snapshot_achievements(self, league: League, user_id: str, client: KickbaseClient) -> None:
        """Kickbase's own counters of the user, to learn how the player achievements are counted."""
        try:
            raw = await client.request("GET", f"/v4/leagues/{league.id}/user/achievements")
        except KickbaseAuthError:
            raise
        except KickbaseError as e:
            log.info("Own achievements not available: %s", e)
            return
        counts: dict[str, int] = {}
        for name, value in learning.parse_achievement_counts(raw).items():
            key = learning.rule_for(name)
            if key:
                counts[key] = value
        await asyncio.to_thread(self._store_snapshot, league, user_id, counts, raw)
        await asyncio.to_thread(self._vote_mode, league, user_id)

    def _store_snapshot(self, league: League, user_id: str, counts: dict, raw: Any) -> None:
        with Session(self.engine) as session:
            last_final = session.exec(
                select(MatchdayRanking.day)
                .where(MatchdayRanking.league_id == league.id, MatchdayRanking.final == True)  # noqa: E712
                .order_by(MatchdayRanking.day.desc())
            ).first()
            previous = session.exec(
                select(AchievementSnapshot)
                .where(AchievementSnapshot.user_id == user_id, AchievementSnapshot.league_id == league.id)
                .order_by(AchievementSnapshot.at.desc())
            ).first()
            ### Only a new snapshot when something changed, the table stays small
            if previous and previous.counts == counts and previous.last_final_day == last_final:
                return
            session.add(
                AchievementSnapshot(
                    user_id=user_id,
                    league_id=league.id,
                    last_final_day=last_final,
                    counts=counts,
                    raw=raw if isinstance(raw, dict) else {"answer": raw},
                )
            )
            session.commit()

    def _vote_mode(self, league: League, user_id: str) -> None:
        from api.insights import Insights

        with Session(self.engine) as session:
            snaps = session.exec(
                select(AchievementSnapshot)
                .where(AchievementSnapshot.user_id == user_id, AchievementSnapshot.league_id == league.id)
                .order_by(AchievementSnapshot.at.desc())
            ).all()
            if len(snaps) < 2:
                return
            new, old = snaps[0], next((s for s in snaps[1:] if s.last_final_day != snaps[0].last_final_day), None)
            if old is None or new.last_final_day is None or old.last_final_day is None:
                return
            days = range(old.last_final_day + 1, new.last_final_day + 1)
            season = Insights(session, league, user_id).achievement_seasons().get(user_id)
            if season is None:
                return
            delta = {k: new.counts.get(k, 0) - old.counts.get(k, 0) for k in learning.PLAYER_RULES if k in new.counts}
            per_day: dict[str, int] = {}
            per_player: dict[str, int] = {}
            for key in learning.PLAYER_RULES:
                threshold = int(key.split("_")[1])
                points = [season.lineup_points.get(d, []) for d in days]
                per_day[key] = sum(1 for p in points if p and max(p) >= threshold)
                per_player[key] = sum(1 for p in points for x in p if x >= threshold)
            votes_day, votes_player = learning.mode_votes(delta, per_day, per_player)
            state = load_state(session, "achievement_mode")
        if not votes_day and not votes_player:
            return
        state["votes_matchday"] = state.get("votes_matchday", 0) + votes_day
        state["votes_player"] = state.get("votes_player", 0) + votes_player
        if abs(state["votes_player"] - state["votes_matchday"]) >= 2:
            state["mode"] = "player" if state["votes_player"] > state["votes_matchday"] else "matchday"
        self._save("achievement_mode", state)
        log.info("Achievement counting: %s", state)

    ### ==============================================================================================
    ### D: instant sales
    ### ==============================================================================================

    def update_sell_ratio(self) -> None:
        with Session(self.engine) as session:
            rows = session.exec(select(AutomationEvent).where(AutomationEvent.kind == "sell")).all()
        observations = [
            (int(r.details.get("received") or 0), int(r.details.get("market_value") or 0)) for r in rows if r.details
        ]
        ratio = learning.sell_ratio(observations)
        if ratio is not None:
            self._save("sell_ratio", {"ratio": ratio, "sales": len(observations)})

    ### ==============================================================================================
    ### E: auctions
    ### ==============================================================================================

    def record_auctions(self, league: League) -> int:
        """Logs every listing once, with every manager's features at that moment."""
        from api.insights import Insights

        with Session(self.engine) as session:
            listings = session.exec(select(MarketListing).where(MarketListing.league_id == league.id)).all()
            if not listings:
                return 0
            known = {
                (row.player_id, row.seller_id)
                for row in session.exec(
                    select(AuctionLog).where(AuctionLog.league_id == league.id, AuctionLog.resolved == False)  # noqa: E712
                )
            }
            new = [item for item in listings if (item.player_id, item.seller_id) not in known]
            if not new:
                return 0
            insights = Insights(session, league, None)
            profiles = insights.bidder_profiles()
            money = insights.balances()
            clubs = insights._club_counts()
            players = {p.id: p for p in session.exec(select(Player).where(Player.id.in_([item.player_id for item in new])))}
            for listing in new:
                player = players.get(listing.player_id)
                if player is None:
                    continue
                price = listing.price or player.market_value
                candidates = {}
                for mid, profile in profiles.items():
                    if mid == listing.seller_id:
                        continue
                    need, interest, activity, full = coach.bidder_features(profile, player.position, player.market_value)
                    candidates[mid] = {
                        "need": need,
                        "interest": interest,
                        "activity": activity,
                        "squad_full": full,
                        "can_buy": clubs.can_buy(mid, player.team_id),
                        "affordable": mid in money and money[mid][1] >= price,
                    }
                session.add(
                    AuctionLog(
                        league_id=league.id,
                        player_id=player.id,
                        listed_at=listing.listed_at or utcnow(),
                        seller_id=listing.seller_id,
                        market_value=player.market_value,
                        price=listing.price,
                        position=player.position,
                        team_id=player.team_id,
                        candidates=candidates,
                    )
                )
            session.commit()
        return len(new)

    def resolve_auctions(self, league: League) -> int:
        now = utcnow()
        with Session(self.engine) as session:
            open_rows = session.exec(
                select(AuctionLog).where(AuctionLog.league_id == league.id, AuctionLog.resolved == False)  # noqa: E712
            ).all()
            if not open_rows:
                return 0
            transfers = session.exec(
                select(Transfer).where(
                    Transfer.league_id == league.id, Transfer.player_id.in_([r.player_id for r in open_rows])
                )
            ).all()
            listed_now = set(
                session.exec(select(MarketListing.player_id).where(MarketListing.league_id == league.id)).all()
            )
            resolved = 0
            for row in open_rows:
                listed = row.listed_at
                sale = next(
                    (
                        t
                        for t in sorted(transfers, key=lambda t: t.date)
                        if t.player_id == row.player_id and listed - timedelta(hours=1) <= t.date <= listed + AUCTION_WINDOW
                    ),
                    None,
                )
                if sale is not None:
                    row.winner_id, row.final_price, row.resolved = sale.buyer_id, sale.price, True
                elif row.player_id not in listed_now and now - listed > AUCTION_WINDOW:
                    ### Gone without a buyer from the league: Kickbase took him back or nobody bid
                    row.resolved = True
                else:
                    continue
                session.add(row)
                resolved += 1
            session.commit()
        return resolved

    def fit_bidder(self, force: bool = False) -> learning.BidderModel | None:
        if not force and not self._due("bidder"):
            return None
        with Session(self.engine) as session:
            rows = session.exec(
                select(AuctionLog).where(AuctionLog.resolved == True, AuctionLog.winner_id.is_not(None))  # noqa: E712
            ).all()
        samples = []
        auctions = 0
        for row in rows:
            if row.winner_id not in row.candidates:
                continue
            auctions += 1
            for mid, c in row.candidates.items():
                if not c.get("can_buy") or not c.get("affordable", True):
                    continue
                features = [float(c.get(name, 0)) for name in learning.BIDDER_FEATURES]
                samples.append((features, 1 if mid == row.winner_id else 0))
        model = learning.fit_bidders(samples, auctions)
        self._save("bidder", {"weights": list(model.weights), "bias": model.bias, "auctions": auctions})
        return model

    ### ==============================================================================================
    ### All of it
    ### ==============================================================================================

    def after_sync(self, league: League) -> None:
        """The synchronous part, run in a worker thread after a league's sync."""
        try:
            self.fill_actuals(league.competition_id)
            self.fit_expectations(league.competition_id)
            self.log_expectations(league)
            self.update_sell_ratio()
            self.resolve_auctions(league)
            self.record_auctions(league)
            self.fit_bidder()
        except Exception:
            log.exception("Learning after the sync of %s failed", league.name)

    def status(self, league: League) -> dict:
        with Session(self.engine) as session:
            weights = load_state(session, "expectation")
            bidder = load_state(session, "bidder")
            mode = load_state(session, "achievement_mode")
            sell = load_state(session, "sell_ratio")
            logged = session.exec(
                select(AuctionLog.resolved).where(AuctionLog.league_id == league.id)
            ).all()
            expectation_logged = session.exec(
                select(ExpectationLog.actual).where(ExpectationLog.competition_id == league.competition_id)
            ).all()
        def camel(data: dict) -> dict:
            return {to_camel(k): v for k, v in data.items()}

        return {
            "expectation": camel(weights),
            "expectation_logged": len(expectation_logged),
            "expectation_checked": sum(1 for a in expectation_logged if a is not None),
            "bidder": camel(bidder),
            "auctions_logged": len(logged),
            "auctions_resolved": sum(1 for r in logged if r),
            "achievement_mode": camel(mode or {"mode": "matchday"}),
            "sell_ratio": camel(sell),
        }

