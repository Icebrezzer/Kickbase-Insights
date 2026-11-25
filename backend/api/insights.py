"""Builds the API responses from the database.

Everything here only reads. The results only change when a sync finishes, so the API caches them
per league, viewer and sync timestamp (see `api.routes`). The viewer matters for what only they may
see: their real budget and their own bids.
"""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from statistics import median

from sqlmodel import Session, select

from api.context import load_context
from api.schemas import (
    AchievementCheckOut,
    AchievementOut,
    BalanceCorrectionOut,
    BalancePointOut,
    BattleEntryOut,
    BattleOut,
    BidAdviceOut,
    BuyOptionOut,
    ChartManager,
    ChartOut,
    FairCurvePointOut,
    FairPlayerOut,
    FairValuesOut,
    FixturesOut,
    LearningOut,
    LostAuctionOut,
    ManagerDetailOut,
    ManagerOut,
    ManagerSquadPlayerOut,
    MarketPlayerOut,
    MatchdayChartsOut,
    MatchOut,
    OverpayManagerOut,
    OverpayOut,
    OverpayPurchaseOut,
    OverpayStatsOut,
    PlayerDetailOut,
    PlayerOut,
    RivalOut,
    RivalProfileOut,
    RivalsOut,
    SeasonPointOut,
    TeamOut,
    TransferOut,
    TurnoverOut,
    ValueSplitOut,
    WatchedPlayerOut,
)
from core import achievements, analytics, coach, learning
from db.models import (
    AchievementSnapshot,
    Battle,
    BattleEntry,
    BidHistory,
    Fixture,
    League,
    LeagueSeason,
    Manager,
    MarketBid,
    MarketListing,
    MarketValueHistory,
    MatchdayLineup,
    MatchdayRanking,
    Player,
    PlayerForm,
    SquadEntry,
    Team,
    Transfer,
    UserLeague,
)
from kickbase.models import ScoutedPlayer
from sync.learning import achievement_mode, bidder_model

### Overpay is read from the purchases of the last weeks once there are enough of them
RECENT_DAYS = 45
### The balance correction never moves an estimate further than this
MAX_CORRECTION = 25_000_000
MIN_RECENT = 5
MIN_RECENT_LEAGUE = 10


class Insights:
    def __init__(
        self,
        session: Session,
        league: League,
        viewer_id: str | None = None,
        model: coach.ForecastModel | None = None,
        max_squad: int = 18,
        max_per_club: int = 3,
    ):
        self.session = session
        self.league = league
        self.league_id = league.id
        self.viewer_id = viewer_id
        self.model = model or coach.ForecastModel()
        self.max_squad = max_squad
        self.max_per_club = max_per_club
        self._match_points: dict[str, list[tuple[int, int]]] | None = None
        self._form_rows: dict[str, list] | None = None
        self._estimates: dict[str, int] | None = None
        self._prizes: dict[str, int] | None = None
        self._purchase_cache: list[analytics.Purchase] | None = None
        self._correction: BalanceCorrectionOut | None = None
        ### Empty until the first sync after an update has stored it
        self.season = session.get(LeagueSeason, league.id) or LeagueSeason(league_id=league.id)

    ### ================================================================================================
    ### Shared lookups
    ### ================================================================================================

    def _managers(self) -> list[Manager]:
        return list(self.session.exec(select(Manager).where(Manager.league_id == self.league_id)))

    def _manager_names(self) -> dict[str, str]:
        """The name of every manager id. For managers who left it is the one stored on their transfers."""
        names: dict[str, str] = {}
        for buyer_id, buyer, seller_id, seller in self.session.exec(
            select(Transfer.buyer_id, Transfer.buyer, Transfer.seller_id, Transfer.seller).where(
                Transfer.league_id == self.league_id
            )
        ):
            if buyer_id and buyer:
                names[buyer_id] = buyer
            if seller_id and seller:
                names[seller_id] = seller
        names.update({m.id: m.name for m in self._managers()})
        return names

    def _histories(self, player_ids: list[str] | None = None) -> dict[str, list]:
        query = select(MarketValueHistory.player_id, MarketValueHistory.points)
        if player_ids is not None:
            query = query.where(MarketValueHistory.player_id.in_(player_ids))
        return dict(self.session.exec(query).all())

    def match_points(self) -> dict[str, list[tuple[int, int]]]:
        """`(market value day, points)` per player from the stored forms, loaded once per answer."""
        if self._match_points is None:
            self._match_points = {
                pid: [(int(m[4]), int(m[1])) for m in matches if len(m) > 4 and m[4] is not None]
                for pid, matches in self.session.exec(select(PlayerForm.player_id, PlayerForm.matches)).all()
            }
        return self._match_points

    def fixture_infos(self) -> list[coach.FixtureInfo]:
        return [
            coach.FixtureInfo(f.day, f.kickoff, f.status, f.team1_id, f.team2_id)
            for f in self.session.exec(
                select(Fixture).where(Fixture.competition_id == self.league.competition_id)
            )
        ]

    def own_budget(self) -> int | None:
        if not self.viewer_id:
            return None
        membership = self.session.get(UserLeague, (self.viewer_id, self.league_id))
        return membership.budget if membership else None

    def estimated_balances(self) -> dict[str, int]:
        """Start money, plus sales, minus purchases, plus the prize money of the season's achievements.
        Login bonuses are not visible."""
        if self._estimates is None:
            events = analytics.transfer_events(self._transfer_records())
            start_money = self.season.start_money if self.season.start_money is not None else analytics.DEFAULT_START_MONEY
            prizes = self.achievement_totals()
            raw = {
                m.id: analytics.estimate_balance(m.id, events, start_money) + prizes.get(m.id, 0)
                for m in self._managers()
            }
            correction = self.balance_correction(raw)
            self._estimates = {mid: value + correction.amount for mid, value in raw.items()}
            self._correction = correction
        return self._estimates

    def balance_correction(self, raw: dict[str, int]) -> BalanceCorrectionOut:
        """What the estimates miss (login bonuses, wrong achievements), learned from the members whose
        real budget is known: the median of real minus estimated, added to everybody's estimate."""
        fresh_since = datetime.now(UTC) - timedelta(days=2)
        known = [
            (m.user_id, m.budget)
            for m in self.session.exec(select(UserLeague).where(UserLeague.league_id == self.league_id))
            if m.budget is not None and m.budget_updated_at is not None and m.budget_updated_at >= fresh_since
        ]
        residuals = [budget - raw[uid] for uid, budget in known if uid in raw]
        if not residuals:
            return BalanceCorrectionOut(amount=0, members=0)
        amount = int(median(residuals))
        amount = max(-MAX_CORRECTION, min(MAX_CORRECTION, amount))
        return BalanceCorrectionOut(amount=amount, members=len(residuals), residuals=sorted(residuals))

    def balances(self) -> dict[str, tuple[int, int]]:
        """Per manager the balance and the highest possible bid. The viewer's own come from the real
        budget, the others are estimates (see `estimated_balances`)."""
        estimates = self.estimated_balances()
        own_budget = self.own_budget()
        result = {}
        for manager in self._managers():
            estimated = estimates.get(manager.id, 0)
            balance = own_budget if manager.id == self.viewer_id and own_budget is not None else estimated
            result[manager.id] = (balance, analytics.max_bid(balance, manager.team_value or 0))
        return result

    ### ================================================================================================
    ### Manager detail
    ### ================================================================================================

    def manager_detail(
        self, manager_id: str, balances: bool, current_lineup: list[str] | None, day: int | None = None
    ) -> ManagerDetailOut | None:
        managers = sorted(self._managers(), key=lambda m: (m.placement is None, m.placement or 0, m.name))
        manager = next((m for m in managers if m.id == manager_id), None)
        if manager is None:
            return None
        index = managers.index(manager)
        squad_entries = {pid: e for pid, e in self._squad().items() if e.manager_id == manager_id}
        lineups = self.lineups_by_day().get(manager_id, {})
        lineup_ids = list(lineups.get(day, [])) if day is not None else list(current_lineup or [])
        if day is None and not lineup_ids and lineups:
            lineup_ids = list(lineups[max(lineups)])
        players = {p.id: p for p in self.session.exec(select(Player).where(Player.id.in_(list(squad_entries))))}
        histories = self._histories(list(squad_entries))
        market_ids = set(self._market())
        all_squad = self._squad()
        points = self.matchday_points()
        forms = self._forms()

        squad_out = []
        for pid in squad_entries:
            player = players.get(pid)
            if player is None:
                continue
            club_matches = sorted((m for m in forms.get(pid, []) if m and m[0] is not None), key=lambda m: m[0])
            out = self._player_out(
                player,
                histories.get(pid),
                all_squad,
                market_ids,
                ManagerSquadPlayerOut,
                in_lineup=pid in lineup_ids,
                form=[(int(m[0]), int(m[1]) if (len(m) < 4 or m[3] in (3, 5) or (m[2] or 0) > 0) else None) for m in club_matches[-5:]],
                starts=sum(1 for m in club_matches[-10:] if len(m) > 3 and m[3] == coach.ROLE_START) if club_matches else None,
                day_points=points.get((pid, day)) if day is not None else None,
            )
            squad_out.append(out)
        squad_out.sort(key=lambda p: (not p.in_lineup, p.position, -(p.average_points or 0)))

        def split(ids: list[str]) -> ValueSplitOut:
            chosen = [p for p in squad_out if p.id in ids]
            return ValueSplitOut(
                team_value=sum(p.market_value for p in chosen), today=sum(p.today or 0 for p in chosen)
            )

        records = self._transfer_records()
        own_records = [t for t in records if manager_id in (t.buyer, t.seller)]
        names = self._manager_names()
        turnovers = [t for t in self.turnovers() if t.manager_id == manager_id or t.manager == manager_id]
        own_purchases = [p for p in self._purchases() if p.transfer.buyer == manager_id]
        earned = achievements.evaluate(
            self.achievement_seasons()[manager_id], achievement_mode(self.session) == "player"
        )
        shown = balances or manager_id == self.viewer_id
        money = self.balances().get(manager_id) if shown else None
        clubs = Counter(p.team_id for p in squad_out if p.team_id)
        rankings = sorted(
            self.session.exec(
                select(MatchdayRanking).where(
                    MatchdayRanking.league_id == self.league_id, MatchdayRanking.manager_id == manager_id
                )
            ),
            key=lambda r: r.day,
        )
        kickoffs: dict[int, datetime] = {}
        for f in self.session.exec(select(Fixture).where(Fixture.competition_id == self.league.competition_id)):
            if f.kickoff and (f.day not in kickoffs or f.kickoff < kickoffs[f.day]):
                kickoffs[f.day] = f.kickoff

        return ManagerDetailOut(
            id=manager.id,
            name=manager.name,
            image=manager.image,
            is_self=manager.id == self.viewer_id,
            placement=manager.placement,
            points=manager.points,
            previous_id=managers[index - 1].id if index > 0 else None,
            next_id=managers[index + 1].id if index + 1 < len(managers) else None,
            transfers=len(own_records),
            squad_size=len(squad_out),
            max_squad=self.max_squad,
            total=split([p.id for p in squad_out]),
            lineup=split(lineup_ids),
            bench=split([p.id for p in squad_out if p.id not in lineup_ids]),
            transfer_profit=sum(t.profit or 0 for t in turnovers),
            overpay_average=(sum(p.overpay_share for p in own_purchases) / len(own_purchases)) if own_purchases else None,
            clubs=clubs.most_common(),
            positions=dict(Counter(p.position for p in squad_out)),
            estimated_balance=money[0] if money else None,
            max_bid=money[1] if money else None,
            lineup_day=day,
            lineup_ids=lineup_ids,
            days=sorted(lineups),
            squad=squad_out,
            turnovers=turnovers,
            transfer_list=[self._transfer_out(t, names) for t in self._own_transfers(manager_id)],
            achievements=[
                AchievementOut(
                    key=e.rule.key,
                    group=e.rule.group,
                    name=e.rule.name,
                    description=e.rule.description,
                    reward=e.rule.reward,
                    kind=e.rule.kind,
                    count=e.count,
                    amount=e.amount,
                )
                for e in earned
            ],
            achievements_total=achievements.total(earned),
            season=[
                SeasonPointOut(day=r.day, points=r.points, season_points=r.season_points, placement=r.placement)
                for r in rankings
            ],
            team_values=self.team_value_history(manager_id),
            matchday_dates=[(d, k.date().isoformat()) for d, k in sorted(kickoffs.items()) if k <= datetime.now(UTC)],
        )

    def _own_transfers(self, manager_id: str) -> list[Transfer]:
        rows = self.session.exec(
            select(Transfer).where(
                Transfer.league_id == self.league_id,
                (Transfer.buyer_id == manager_id) | (Transfer.seller_id == manager_id),
            )
        ).all()
        return sorted((t for t in rows if self._this_season(t)), key=lambda t: t.date, reverse=True)

    def team_value_history(self, manager_id: str) -> list[tuple[str, int]]:
        """The team value every evening since the season start: the squad of that day at that day's values.

        The squad is rebuilt backwards from today's through the transfers: a purchase after a day means
        the player was not there yet, a sale after it means he still was.
        """
        start = self.season_start()
        if start is None:
            return []
        today = analytics.market_value_day(datetime.now(UTC))
        first = analytics.market_value_day(start)
        squad = {pid for pid, e in self._squad().items() if e.manager_id == manager_id}
        events = sorted(
            (e for e in analytics.transfer_events(self._transfer_records()) if e.manager == manager_id),
            key=lambda e: e.date,
            reverse=True,
        )
        involved = squad | {e.player_id for e in events}
        histories = self._histories(list(involved))
        result = []
        held = set(squad)
        pending = deque(events)
        for day in range(today, first - 1, -1):
            ### Undo everything that happened after this day's market value update
            while pending and analytics.market_value_day(pending[0].date) >= day:
                event = pending.popleft()
                if event.kind == "buy":
                    held.discard(event.player_id)
                else:
                    held.add(event.player_id)
            value = sum(analytics.value_on_day(histories.get(pid) or [], day) or 0 for pid in held)
            result.append((analytics.day_to_date(day).isoformat(), value))
        result.reverse()
        return result

    ### ================================================================================================
    ### Achievements
    ### ================================================================================================

    def _forms(self) -> dict[str, list]:
        if self._form_rows is None:
            self._form_rows = dict(self.session.exec(select(PlayerForm.player_id, PlayerForm.matches)).all())
        return self._form_rows

    def matchday_points(self) -> dict[tuple[str, int], int]:
        """(player, matchday) -> Kickbase points, for every player whose form is stored."""
        return {
            (pid, int(m[0])): int(m[1])
            for pid, matches in self._forms().items()
            for m in matches
            if m and m[0] is not None
        }

    def lineups_by_day(self) -> dict[str, dict[int, list[str]]]:
        result: dict[str, dict[int, list[str]]] = defaultdict(dict)
        for row in self.session.exec(select(MatchdayLineup).where(MatchdayLineup.league_id == self.league_id)):
            result[row.manager_id][row.day] = list(row.players)
        return result

    def achievement_seasons(self) -> dict[str, achievements.ManagerSeason]:
        rankings: dict[str, list] = defaultdict(list)
        for r in self.session.exec(select(MatchdayRanking).where(MatchdayRanking.league_id == self.league_id)):
            rankings[r.manager_id].append((r.day, r.points, r.placement, r.team_value))
        points = self.matchday_points()
        best: dict[int, tuple[int, set[str]]] = {}
        for (pid, day), value in points.items():
            top = best.get(day)
            if top is None or value > top[0]:
                best[day] = (value, {pid})
            elif value == top[0]:
                top[1].add(pid)
        best_by_day = {day: ids for day, (_, ids) in best.items()}
        lineups = self.lineups_by_day()
        records = self._transfer_records()
        turnovers = self._turnovers()
        squad_sizes = Counter(e.manager_id for e in self._squad().values())
        result = {}
        for manager in self._managers():
            own_lineups = lineups.get(manager.id, {})
            result[manager.id] = achievements.ManagerSeason(
                manager_id=manager.id,
                matchdays=sorted(rankings.get(manager.id, [])),
                season_points=manager.points or 0,
                lineup_points={day: [points.get((pid, day), 0) for pid in ids] for day, ids in own_lineups.items()},
                mvp_days=achievements.mvp_days(own_lineups, best_by_day),
                profits=[t.profit for t in turnovers if t.manager == manager.id and t.profit is not None],
                transfers=sum(1 for t in records if manager.id in (t.buyer, t.seller)),
                squad_size=squad_sizes.get(manager.id, 0),
            )
        return result

    def learning_view(self, status: dict) -> LearningOut:
        """What the app has learned, with the viewer's own achievements next to Kickbase's counters."""
        self.estimated_balances()
        checks: list[AchievementCheckOut] = []
        checked_at = None
        if self.viewer_id:
            snapshot = self.session.exec(
                select(AchievementSnapshot)
                .where(AchievementSnapshot.user_id == self.viewer_id, AchievementSnapshot.league_id == self.league_id)
                .order_by(AchievementSnapshot.at.desc())
            ).first()
            season = self.achievement_seasons().get(self.viewer_id)
            if season is not None:
                own = {
                    e.rule.key: e
                    for e in achievements.evaluate(season, achievement_mode(self.session) == "player")
                }
                for rule in achievements.RULES:
                    kickbase = snapshot.counts.get(rule.key) if snapshot else None
                    checks.append(
                        AchievementCheckOut(key=rule.key, name=rule.name, kickbase=kickbase, app=own[rule.key].count)
                    )
            checked_at = snapshot.at if snapshot else None
        return LearningOut(
            **status,
            balance_correction=self._correction,
            achievements=checks,
            achievements_checked_at=checked_at,
        )

    def achievement_totals(self) -> dict[str, int]:
        if self._prizes is None:
            per_player = achievement_mode(self.session) == "player"
            self._prizes = {
                mid: achievements.total(achievements.evaluate(season, per_player))
                for mid, season in self.achievement_seasons().items()
            }
        return self._prizes

    def season_start(self) -> datetime | None:
        """The start Kickbase reports. Otherwise the first stored transfer or the first kick-off."""
        if self.season.started_at:
            return self.season.started_at
        first_transfer = self.session.exec(
            select(Transfer.date).where(Transfer.league_id == self.league_id).order_by(Transfer.date).limit(1)
        ).first()
        first_kickoff = self.session.exec(
            select(Fixture.kickoff)
            .where(Fixture.competition_id == self.league.competition_id, Fixture.kickoff.is_not(None))
            .order_by(Fixture.kickoff)
            .limit(1)
        ).first()
        candidates = [d for d in (first_transfer, first_kickoff) if d is not None]
        return min(candidates) if candidates else None

    def _this_season(self, transfer: Transfer) -> bool:
        """Only the start Kickbase reports cuts transfers off, a guessed start drops nothing."""
        return self.season.started_at is None or transfer.date >= self.season.started_at

    def _transfer_records(self) -> list[analytics.TransferRecord]:
        rows = self.session.exec(select(Transfer).where(Transfer.league_id == self.league_id))
        records = [
            analytics.TransferRecord(
                t.id,
                t.date,
                t.player_id,
                t.player_name,
                t.team_id,
                t.buyer_id or t.buyer,
                t.seller_id or t.seller,
                t.price,
            )
            for t in rows
        ]
        return analytics.transfers_since(records, self.season.started_at)

    def _purchases(self) -> list[analytics.Purchase]:
        if self._purchase_cache is None:
            records = self._transfer_records()
            histories = self._histories(list({t.player_id for t in records}))
            self._purchase_cache = analytics.kickbase_purchases(records, lambda player_id: histories.get(player_id) or [])
        return self._purchase_cache

    def _player_out(
        self,
        player: Player,
        mv_history: list | None,
        squad: dict[str, SquadEntry],
        market_ids: set[str],
        model: type[PlayerOut] = PlayerOut,
        **extra,
    ) -> PlayerOut:
        owner = squad.get(player.id)
        prediction = (
            coach.forecast(mv_history, self.model, matches=self.match_points().get(player.id))
            if mv_history
            else None
        )
        return model(
            id=player.id,
            first_name=player.first_name,
            last_name=player.last_name,
            team_id=player.team_id,
            image=player.image,
            position=player.position,
            status=player.status,
            status_text=player.status_text,
            market_value=player.market_value,
            trend=player.market_value_trend,
            total_points=player.total_points,
            average_points=player.average_points,
            goals=player.goals,
            assists=player.assists,
            active=player.active,
            owner_id=owner.manager_id if owner else None,
            purchase_price=owner.purchase_price if owner else None,
            on_market=player.id in market_ids,
            **analytics.market_value_deltas(mv_history or []),
            forecast=prediction.next_change if prediction else None,
            projection=list(prediction.projection) if prediction else [],
            **extra,
        )

    def _squad(self) -> dict[str, SquadEntry]:
        return {
            e.player_id: e
            for e in self.session.exec(select(SquadEntry).where(SquadEntry.league_id == self.league_id))
        }

    def _market(self) -> dict[str, MarketListing]:
        return {
            listing.player_id: listing
            for listing in self.session.exec(
                select(MarketListing).where(MarketListing.league_id == self.league_id)
            )
        }

    ### ================================================================================================
    ### Endpoints
    ### ================================================================================================

    def teams(self) -> list[TeamOut]:
        teams = self.session.exec(
            select(Team).where(Team.competition_id == self.league.competition_id).order_by(Team.placement)
        )
        return [TeamOut.model_validate(team) for team in teams]

    def players(self) -> list[PlayerOut]:
        squad = self._squad()
        market = self._market()
        histories = self._histories()
        result = []
        for player in self.session.exec(select(Player)):
            ### Players who left the competition only matter while someone still owns or sells them
            if not player.active and player.id not in squad and player.id not in market:
                continue
            result.append(self._player_out(player, histories.get(player.id), squad, set(market)))
        result.sort(key=lambda p: p.market_value, reverse=True)
        return result

    def player(self, player_id: str) -> PlayerDetailOut | None:
        player = self.session.get(Player, player_id)
        if player is None:
            return None
        history = self._histories([player_id]).get(player_id) or []
        names = self._manager_names()
        transfers = self.session.exec(
            select(Transfer)
            .where(Transfer.league_id == self.league_id, Transfer.player_id == player_id)
            .order_by(Transfer.date.desc())
        )
        return self._player_out(
            player,
            history,
            self._squad(),
            set(self._market()),
            PlayerDetailOut,
            history=[(analytics.day_to_date(day).isoformat(), value) for day, value in history],
            transfers=[self._transfer_out(t, names) for t in transfers if self._this_season(t)],
        )

    ### ================================================================================================
    ### Rivals, bidders and the market
    ### ================================================================================================

    def _club_counts(self) -> coach.ClubCounts:
        return coach.ClubCounts.build(
            (entry.manager_id, team_id)
            for entry, team_id in self.session.exec(
                select(SquadEntry, Player.team_id)
                .join(Player, Player.id == SquadEntry.player_id)
                .where(SquadEntry.league_id == self.league_id)
            )
        )

    def bidder_profiles(self, purchases: list[analytics.Purchase] | None = None) -> dict[str, coach.BidderProfile]:
        """What every manager did on the market: overpay, price classes, activity and squad shape."""
        purchases = purchases if purchases is not None else self._purchases()
        recent_since = datetime.now(UTC) - timedelta(days=14)
        records = self._transfer_records()
        fit_positions: dict[str, Counter] = defaultdict(Counter)
        sizes: Counter = Counter()
        for entry, position, status in self.session.exec(
            select(SquadEntry, Player.position, Player.status)
            .join(Player, Player.id == SquadEntry.player_id)
            .where(SquadEntry.league_id == self.league_id)
        ):
            sizes[entry.manager_id] += 1
            if status in coach.STATUS_AVAILABILITY:
                fit_positions[entry.manager_id][position] += 1
        result = {}
        recent_cut = datetime.now(UTC) - timedelta(days=RECENT_DAYS)
        for manager in self._managers():
            own = [p for p in purchases if p.transfer.buyer == manager.id]
            ### Prices rise during a season: the recent purchases count when there are enough of them
            fresh = [p for p in own if p.transfer.date >= recent_cut]
            if len(fresh) >= MIN_RECENT:
                own = fresh
            result[manager.id] = coach.BidderProfile(
                manager_id=manager.id,
                overpay_shares=tuple(p.overpay_share for p in own),
                purchase_values=tuple(p.market_value for p in own),
                purchases_recent=sum(1 for t in records if t.buyer == manager.id and t.date >= recent_since),
                positions=dict(fit_positions[manager.id]),
                squad_size=sizes[manager.id],
                max_squad=self.max_squad,
            )
        return result

    def auctions(self) -> list[tuple[datetime, str, int, int]]:
        """Every purchase from Kickbase in this league: (date, player, price paid, market value then).
        The real auctions the backtest replays."""
        return [(p.transfer.date, p.transfer.player_id, p.transfer.price, p.market_value) for p in self._purchases()]

    def winning_shares(self) -> list[tuple[int, float]]:
        """`(market value, markup share)` of every purchase from Kickbase another manager won in this
        league, recent ones (45 days) when there are enough: what it took to win an auction here."""
        rival = [p for p in self._purchases() if p.transfer.buyer != self.viewer_id]
        cut = datetime.now(UTC) - timedelta(days=RECENT_DAYS)
        fresh = [p for p in rival if p.transfer.date >= cut]
        return [(p.market_value, p.overpay_share) for p in (fresh if len(fresh) >= MIN_RECENT_LEAGUE else rival)]

    def market(self, balances: bool = False) -> list[MarketPlayerOut]:
        """`balances` uses the estimated budgets of the others: who cannot pay is no rival, and the
        expected bids are capped by what each can afford."""
        listings = self._market()
        players = {p.id: p for p in self.session.exec(select(Player).where(Player.id.in_(list(listings))))}
        histories = self._histories(list(listings))
        squad = self._squad()
        own_bids = (
            dict(
                self.session.exec(
                    select(MarketBid.player_id, MarketBid.price).where(
                        MarketBid.league_id == self.league_id, MarketBid.user_id == self.viewer_id
                    )
                ).all()
            )
            if self.viewer_id
            else {}
        )
        purchases = self._purchases()
        ### Advice comes from others only
        rival_purchases = [p for p in purchases if p.transfer.buyer != self.viewer_id]
        recent_cut = datetime.now(UTC) - timedelta(days=RECENT_DAYS)
        fresh = [p for p in rival_purchases if p.transfer.date >= recent_cut]
        league_shares = [p.overpay_share for p in (fresh if len(fresh) >= MIN_RECENT_LEAGUE else rival_purchases)]
        learned = bidder_model(self.session)
        gaps = learning.lost_gaps(
            (a.own_bid, a.own_bid, a.price) for a in self.lost_auctions() if a.date >= recent_cut
        )
        clubs = self._club_counts()
        managers = {m.id: m for m in self._managers()}
        squad_sizes = Counter(e.manager_id for e in squad.values())
        money = self.balances()
        profiles = self.bidder_profiles(purchases)
        now = datetime.now(UTC)
        context = load_context(self.session, self.league.competition_id, list(listings), now)
        upcoming = context.upcoming
        updates = coach.updates_until(upcoming.deadline if upcoming else None, now)
        own_max_bid = money[self.viewer_id][1] if self.viewer_id in money else None
        result = []
        for listing in listings.values():
            player = players.get(listing.player_id)
            if player is None:
                continue
            is_free_agent = listing.seller_id is None
            price = listing.price or player.market_value
            advice = analytics.bid_advice(rival_purchases, player.market_value) if is_free_agent else None
            estimates = []
            for mid in managers:
                if mid in (self.viewer_id, listing.seller_id) or mid not in profiles:
                    continue
                estimate = coach.estimate_bidder(
                    profiles[mid],
                    player.position,
                    player.market_value,
                    price,
                    clubs.can_buy(mid, player.team_id, self.max_per_club),
                    money[mid][1] if balances and mid in money else None,
                    league_shares,
                    learned.probability if learned.learned else None,
                )
                if estimate.probability > 0:
                    estimates.append(estimate)
            estimates.sort(key=lambda e: -e.probability)
            matches = context.match_points(player.id)
            prediction = coach.forecast(histories.get(player.id) or [], self.model, max(updates, 1), matches)
            gain = prediction.projection[updates - 1] if prediction and updates > 0 else None
            margin = None if gain is None else gain - max(price - player.market_value, 0)
            bids = coach.bid_range(
                player.market_value,
                price,
                league_shares,
                estimates,
                gain,
                own_max_bid,
                gaps.get(coach.price_class(player.market_value)),
            )
            own_club = clubs.of(self.viewer_id or "", player.team_id)
            expectation = context.expectation(player.id, player.position, player.status, player.team_id, player.average_points)
            fixture = context.fixture_of(player.team_id)
            odds = context.odds_of(fixture)
            result.append(
                self._player_out(
                    player,
                    histories.get(player.id),
                    squad,
                    set(listings),
                    MarketPlayerOut,
                    seller_id=listing.seller_id,
                    seller_name=listing.seller_name,
                    price=listing.price,
                    offer_count=listing.offer_count,
                    own_bid=own_bids.get(listing.player_id),
                    expires_at=listing.expires_at,
                    listed_at=listing.listed_at,
                    is_free_agent=is_free_agent,
                    bid_advice=BidAdviceOut.model_validate(advice) if advice else None,
                    rivals=[
                        RivalOut(
                            manager_id=e.manager_id,
                            name=managers[e.manager_id].name,
                            image=managers[e.manager_id].image,
                            club_players=clubs.of(e.manager_id, player.team_id),
                            squad_size=squad_sizes.get(e.manager_id, 0),
                            estimated_balance=money[e.manager_id][0] if balances and e.manager_id in money else None,
                            max_bid=money[e.manager_id][1] if balances and e.manager_id in money else None,
                            probability=e.probability,
                            expected_bid=e.expected_bid,
                            reasons=list(e.reasons),
                            in_minus=balances and e.manager_id in money and money[e.manager_id][0] < 0,
                        )
                        for e in estimates
                    ],
                    rivals_by_budget=balances,
                    own_club_players=own_club,
                    own_club_full=own_club >= self.max_per_club,
                    margin_to_matchday=margin,
                    updates_to_matchday=updates,
                    bid_low=bids.low,
                    bid_high=bids.high,
                    margin_low=bids.margin_low,
                    margin_high=bids.margin_high,
                    expected_points=expectation.expected,
                    play_probability=expectation.play_probability,
                    next_opponent_id=expectation.opponent_id,
                    next_home=expectation.home,
                    odds=list(odds) if odds else None,
                    bidders_learned=learned.learned,
                    seller_in_minus=bool(
                        balances and listing.seller_id in money and money[listing.seller_id][0] < 0
                    ),
                )
            )
        far_future = datetime.max.replace(tzinfo=UTC)
        result.sort(key=lambda p: (p.expires_at or far_future, -p.market_value))
        return result

    def lost_auctions(self) -> list[LostAuctionOut]:
        """Auctions the viewer bid in and another manager won."""
        if not self.viewer_id:
            return []
        bids = self.session.exec(
            select(BidHistory).where(BidHistory.league_id == self.league_id, BidHistory.user_id == self.viewer_id)
        ).all()
        if not bids:
            return []
        names = self._manager_names()
        transfers = self.session.exec(
            select(Transfer).where(
                Transfer.league_id == self.league_id, Transfer.player_id.in_([b.player_id for b in bids])
            )
        ).all()
        result = []
        for bid in bids:
            won = next(
                (
                    t
                    for t in sorted(transfers, key=lambda t: t.date)
                    if t.player_id == bid.player_id
                    and bid.first_seen - timedelta(days=1) <= t.date <= bid.last_seen + timedelta(days=2)
                ),
                None,
            )
            if won is None or not won.buyer_id or won.buyer_id == self.viewer_id:
                continue
            result.append(
                LostAuctionOut(
                    player_id=bid.player_id,
                    player_name=won.player_name,
                    date=won.date,
                    own_bid=bid.price,
                    price=won.price,
                    winner_id=won.buyer_id,
                    winner=names.get(won.buyer_id, won.buyer or "?"),
                )
            )
        result.sort(key=lambda a: a.date, reverse=True)
        return result

    def rival_profiles(self, balances: bool) -> RivalsOut:
        """Every manager as a bidder: habits, needs, weaknesses and money."""
        purchases = self._purchases()
        profiles = self.bidder_profiles(purchases)
        money = self.balances()
        clubs = self._club_counts()
        records = self._transfer_records()
        events = analytics.transfer_events(records)
        start_money = self.season.start_money if self.season.start_money is not None else analytics.DEFAULT_START_MONEY
        lost = self.lost_auctions()
        now = datetime.now(UTC)
        context = load_context(self.session, self.league.competition_id, [], now)
        squads: dict[str, list[Player]] = defaultdict(list)
        for entry, player in self.session.exec(
            select(SquadEntry, Player)
            .join(Player, Player.id == SquadEntry.player_id)
            .where(SquadEntry.league_id == self.league_id)
        ):
            squads[entry.manager_id].append(player)

        def overpay_by_class(shares_values: list[tuple[float, int]]) -> list[float | None]:
            result: list[float | None] = []
            for index in range(len(coach.PRICE_CLASSES)):
                values = [share for share, value in shares_values if coach.price_class(value) == index]
                result.append(median(values) if values else None)
            return result

        league_overpay = overpay_by_class([(p.overpay_share, p.market_value) for p in purchases])
        out = []
        for manager in self._managers():
            profile = profiles[manager.id]
            own_purchases = [p for p in purchases if p.transfer.buyer == manager.id]
            hours = Counter(
                t.date.astimezone(analytics.MARKET_VALUE_TIMEZONE).hour for t in records if t.buyer == manager.id
            )
            unavailable = [p for p in squads[manager.id] if p.status not in coach.STATUS_AVAILABILITY]
            needs = [pos for pos in coach.IDEAL_SQUAD if coach.position_need(profile, pos) >= 0.5]
            shown = balances or manager.id == self.viewer_id
            history = []
            if shown:
                balance = start_money
                for event in sorted((e for e in events if e.manager == manager.id), key=lambda e: e.date):
                    balance += event.price if event.kind == "sell" else -event.price
                    history.append((event.date, balance))
            balance_now = money.get(manager.id, (None, None))
            last = max((t.date for t in records if manager.id in (t.buyer, t.seller)), default=None)
            out.append(
                RivalProfileOut(
                    id=manager.id,
                    name=manager.name,
                    image=manager.image,
                    is_self=manager.id == self.viewer_id,
                    squad_size=profile.squad_size,
                    fit_positions={pos: profile.positions.get(pos, 0) for pos in coach.IDEAL_SQUAD},
                    needs=needs,
                    unavailable=[p.id for p in unavailable],
                    blocked_clubs=[
                        team
                        for team, count in clubs.counts.get(manager.id, Counter()).items()
                        if count >= self.max_per_club
                    ],
                    purchases=len(own_purchases),
                    purchases_recent=profile.purchases_recent,
                    overpay_median=median(profile.overpay_shares) if profile.overpay_shares else None,
                    overpay_by_class=overpay_by_class([(p.overpay_share, p.market_value) for p in own_purchases]),
                    active_hours=[hour for hour, _ in hours.most_common(3)],
                    last_activity=last,
                    estimated_balance=balance_now[0] if shown else None,
                    max_bid=balance_now[1] if shown else None,
                    in_minus=bool(shown and balance_now[0] is not None and balance_now[0] < 0),
                    balance_history=[BalancePointOut(date=d, balance=b) for d, b in history[-60:]],
                    lost_to=[a for a in lost if a.winner_id == manager.id],
                )
            )
        out.sort(key=lambda r: (not r.is_self, -(r.purchases_recent or 0)))
        return RivalsOut(
            league_overpay_by_class=league_overpay,
            price_classes=[high for _, high in coach.PRICE_CLASSES[:-1]],
            deadline=context.upcoming.deadline if context.upcoming else None,
            managers=out,
            lost=lost,
        )

    def buy_options(self) -> list[BuyOptionOut]:
        """Market players worth buying now: value gain until the deadline and more expected points."""
        if not self.viewer_id:
            return []
        market = {p.id: p for p in self.market(balances=False)}
        own_ids = [pid for pid, e in self._squad().items() if e.manager_id == self.viewer_id]
        now = datetime.now(UTC)
        context = load_context(self.session, self.league.competition_id, [*own_ids, *market], now)
        own_players = list(self.session.exec(select(Player).where(Player.id.in_(own_ids))))
        squad = [
            coach.LineupCandidate(
                p.id,
                p.position,
                context.expectation(p.id, p.position, p.status, p.team_id, p.average_points).expected,
                p.market_value,
            )
            for p in own_players
        ]
        money = self.balances()
        own_max = money.get(self.viewer_id, (None, None))[1]
        result = []
        for player in market.values():
            if player.seller_id == self.viewer_id:
                continue
            candidate = coach.LineupCandidate(player.id, player.position, player.expected_points or 0.0, player.market_value)
            blocked = None
            if player.own_club_full:
                blocked = f"Vereinslimit erreicht ({self.max_per_club})"
            elif len(own_ids) >= self.max_squad:
                blocked = "Kader voll – erst verkaufen"
            elif own_max is not None and (player.bid_low or 0) > own_max:
                blocked = "Max. Gebot reicht nicht"
            result.append(
                BuyOptionOut(
                    player=player,
                    bid=player.bid_low or player.price or player.market_value,
                    margin=player.margin_low,
                    points_gain=coach.points_gain(squad, candidate),
                    blocked=blocked,
                )
            )
        result.sort(key=lambda o: (o.blocked is not None, -((o.margin or 0) + o.points_gain * 10_000)))
        return result

    def watchlist(self, scouted: list[ScoutedPlayer]) -> list[WatchedPlayerOut]:
        """Add players to the viewer's watchlist."""
        player_ids = [entry.id for entry in scouted]
        players = {p.id: p for p in self.session.exec(select(Player).where(Player.id.in_(player_ids)))}
        histories = self._histories(player_ids)
        squad = self._squad()
        listings = self._market()
        result = []
        for entry in scouted:
            player = players.get(entry.id)
            if player is None:
                ### Not synced yet, so we only know what Kickbase sent
                result.append(
                    WatchedPlayerOut(
                        id=entry.id,
                        last_name=entry.last_name,
                        team_id=entry.team_id,
                        image=entry.image,
                        position=entry.position,
                        status=entry.status,
                        market_value=round(entry.market_value),
                        trend=0,
                        on_market=entry.on_market,
                    )
                )
                continue
            listing = listings.get(player.id)
            result.append(
                self._player_out(
                    player,
                    histories.get(player.id),
                    squad,
                    set(listings),
                    WatchedPlayerOut,
                    expires_at=listing.expires_at if listing else None,
                )
            )
        return result

    def fair_values(self) -> FairValuesOut:
        ### Only this competition: the player table can hold more than one
        team_ids = self.session.exec(
            select(Team.id).where(Team.competition_id == self.league.competition_id)
        ).all()
        players = self.session.exec(
            select(Player).where(Player.active, Player.team_id.in_(team_ids), Player.market_value > 0)
        ).all()
        games = {p.id: analytics.games_played(p.total_points, p.average_points) for p in players}
        needed = analytics.regular_games(games.values())
        regulars = [
            p
            for p in players
            if games[p.id] >= needed and p.average_points and p.position in analytics.POSITIONS
        ]
        curve = analytics.fair_curve(
            [analytics.FairInput(p.position, p.average_points, p.market_value) for p in regulars]
        )
        if curve is None:
            return FairValuesOut(min_games=needed, band=analytics.FAIR_BAND)

        squad = self._squad()
        market = set(self._market())
        histories = self._histories([p.id for p in regulars])
        result = []
        for player in regulars:
            fair_value = curve.value(player.position, player.average_points)
            gap = player.market_value / fair_value - 1
            result.append(
                self._player_out(
                    player,
                    histories.get(player.id),
                    squad,
                    market,
                    FairPlayerOut,
                    games=games[player.id],
                    fair_value=fair_value,
                    gap=gap,
                    rating=analytics.fair_rating(gap),
                )
            )
        result.sort(key=lambda p: p.gap)
        return FairValuesOut(
            min_games=needed,
            band=analytics.FAIR_BAND,
            typical_gap=median(abs(p.gap) for p in result),
            players=result,
            curves={
                position: [FairCurvePointOut(points=x, value=y) for x, y in curve.line(position)]
                for position in curve.offsets
            },
        )

    def _transfer_out(self, t: Transfer, names: dict[str, str]) -> TransferOut:
        return TransferOut(
            id=t.id,
            date=t.date,
            player_id=t.player_id,
            player_name=t.player_name,
            team_id=t.team_id,
            buyer=names.get(t.buyer_id, t.buyer),
            buyer_id=t.buyer_id,
            seller=names.get(t.seller_id, t.seller),
            seller_id=t.seller_id,
            price=t.price,
        )

    def transfers(self) -> list[TransferOut]:
        names = self._manager_names()
        rows = self.session.exec(
            select(Transfer).where(Transfer.league_id == self.league_id).order_by(Transfer.date.desc())
        )
        return [self._transfer_out(t, names) for t in rows if self._this_season(t)]

    def _turnovers(self) -> list[analytics.Turnover]:
        season_start = self.season_start()
        start_day = analytics.market_value_day(season_start) if season_start else None
        events = analytics.transfer_events(self._transfer_records())
        sold_ids = list({e.player_id for e in events if e.kind == "sell"})
        histories = self._histories(sold_ids)

        def starter_price(player_id: str) -> int | None:
            if start_day is None:
                return None
            return analytics.value_on_day(histories.get(player_id) or [], start_day)

        return analytics.pair_turnovers(events, starter_price, season_start)

    def turnovers(self) -> list[TurnoverOut]:
        names = self._manager_names()
        turnovers = self._turnovers()
        players = {
            p.id: p
            for p in self.session.exec(
                select(Player).where(Player.id.in_(list({t.player_id for t in turnovers})))
            )
        }
        result = []
        for t in turnovers:
            player = players.get(t.player_id)
            result.append(
                TurnoverOut(
                    manager=names.get(t.manager, t.manager),
                    manager_id=t.manager if t.manager in names else None,
                    player_id=t.player_id,
                    player_name=(player.last_name if player else None) or t.player_name,
                    first_name=player.first_name if player else None,
                    image=player.image if player else None,
                    team_id=t.team_id or (player.team_id if player else None),
                    position=player.position if player else None,
                    buy_price=t.buy_price,
                    buy_date=t.buy_date,
                    bought_from=names.get(t.bought_from, t.bought_from),
                    starter=t.starter,
                    sell_price=t.sell_price,
                    sell_date=t.sell_date,
                    sold_to=names.get(t.sold_to, t.sold_to),
                    profit=t.profit,
                    days_held=t.days_held,
                )
            )
        result.sort(key=lambda t: t.sell_date, reverse=True)
        return result

    def overpay(self) -> OverpayOut:
        purchases = self._purchases()
        if not purchases:
            return OverpayOut()
        names = self._manager_names()
        player_ids = list({p.transfer.player_id for p in purchases})
        players = {p.id: p for p in self.session.exec(select(Player).where(Player.id.in_(player_ids)))}

        by_manager: dict[str, list[analytics.Purchase]] = defaultdict(list)
        for purchase in purchases:
            by_manager[purchase.transfer.buyer].append(purchase)
        managers = [
            OverpayManagerOut(
                manager=names.get(manager, manager),
                manager_id=manager if manager in names else None,
                **asdict(analytics.overpay_stats(own)),
            )
            for manager, own in by_manager.items()
        ]
        managers.sort(key=lambda m: m.median, reverse=True)

        rows = []
        for purchase in sorted(purchases, key=lambda p: p.transfer.date, reverse=True):
            t = purchase.transfer
            player = players.get(t.player_id)
            rows.append(
                OverpayPurchaseOut(
                    id=t.id,
                    date=t.date,
                    manager=names.get(t.buyer, t.buyer),
                    manager_id=t.buyer if t.buyer in names else None,
                    player_id=t.player_id,
                    player_name=(player.last_name if player else None) or t.player_name,
                    first_name=player.first_name if player else None,
                    image=player.image if player else None,
                    team_id=t.team_id or (player.team_id if player else None),
                    position=player.position if player else None,
                    price=t.price,
                    market_value=purchase.market_value,
                    overpay=purchase.overpay,
                    overpay_share=purchase.overpay_share,
                )
            )
        return OverpayOut(
            league=OverpayStatsOut.model_validate(analytics.overpay_stats(purchases)),
            managers=managers,
            purchases=rows,
        )

    def managers(self, balances: bool = True) -> list[ManagerOut]:
        """Without `balances` the estimated balances and max bids of the others stay empty, the
        viewer's own figures are always there."""
        managers = self._managers()
        events = analytics.transfer_events(self._transfer_records())
        turnovers = self._turnovers()
        squad_sizes = Counter(e.manager_id for e in self._squad().values())
        start_money = self.season.start_money if self.season.start_money is not None else analytics.DEFAULT_START_MONEY
        ### The real budget is private, it is only ever shown to its owner
        own_budget = None
        if self.viewer_id:
            membership = self.session.get(UserLeague, (self.viewer_id, self.league_id))
            own_budget = membership.budget if membership else None

        managers.sort(key=lambda m: (m.points is None, -(m.points or 0)))
        leader_points = managers[0].points if managers and managers[0].points is not None else None
        result = []
        previous_points: int | None = None
        for manager in managers:
            own_events = [e for e in events if e.manager == manager.id]
            estimated = self.estimated_balances().get(manager.id, start_money)
            is_self = manager.id == self.viewer_id
            budget = own_budget if is_self else None
            balance = budget if budget is not None else estimated
            shown = balances or is_self
            profits = [t.profit for t in turnovers if t.manager == manager.id and t.profit is not None]
            result.append(
                ManagerOut(
                    id=manager.id,
                    name=manager.name,
                    image=manager.image,
                    is_self=is_self,
                    placement=manager.placement,
                    points=manager.points,
                    points_behind=(
                        previous_points - manager.points
                        if previous_points is not None and manager.points is not None
                        else 0
                        if leader_points is not None
                        else None
                    ),
                    average_points=manager.average_points,
                    team_value=manager.team_value,
                    matchday_wins=manager.matchday_wins,
                    budget=budget,
                    estimated_balance=estimated if shown else None,
                    max_bid=analytics.max_bid(balance, manager.team_value or 0) if shown else None,
                    squad_size=squad_sizes.get(manager.id, 0),
                    transfers=len(own_events),
                    bought=sum(1 for e in own_events if e.kind == "buy"),
                    sold=sum(1 for e in own_events if e.kind == "sell"),
                    transfer_profit=sum(profits) if profits else 0,
                )
            )
            previous_points = manager.points
        return result

    def battles(self) -> list[BattleOut]:
        managers = {m.id: m for m in self._managers()}
        battles = self.session.exec(
            select(Battle).where(Battle.league_id == self.league_id).order_by(Battle.sort_order)
        ).all()
        entries = self.session.exec(select(BattleEntry).where(BattleEntry.league_id == self.league_id)).all()
        result = []
        for battle in battles:
            rows = [e for e in entries if e.type == battle.type]
            rows.sort(key=lambda e: (e.placement is None, e.placement or 0))
            result.append(
                BattleOut(
                    type=battle.type,
                    name=battle.name,
                    description=battle.description,
                    entries=[
                        BattleEntryOut(
                            manager_id=e.manager_id,
                            name=managers[e.manager_id].name if e.manager_id in managers else e.manager_id,
                            image=managers[e.manager_id].image if e.manager_id in managers else None,
                            placement=e.placement,
                            value=e.value,
                        )
                        for e in rows
                    ],
                )
            )
        return result

    def _chart_managers(self) -> list[ChartManager]:
        return [
            ChartManager(id=m.id, name=m.name)
            for m in sorted(self._managers(), key=lambda m: m.name.casefold())
        ]

    def revenue_chart(self) -> ChartOut:
        managers = self._chart_managers()
        turnovers = self._turnovers()
        start = self.season_start() or (min((t.sell_date for t in turnovers), default=datetime.now(UTC)))
        rows = analytics.cumulative_profit_rows(
            turnovers, [m.id for m in managers], start.astimezone(UTC).date(), datetime.now(UTC).date()
        )
        return ChartOut(managers=managers, rows=rows)

    def wealth_chart(self, balances: bool) -> ChartOut:
        """Comparable trading/valuation history, excluding undated rewards and login bonuses.

        A missing historical player value is a gap, never zero. Cash and squad are both
        reconstructed at the market value update boundary to avoid counting a trade twice.
        """
        managers = [m for m in self._chart_managers() if balances or m.id == self.viewer_id]
        start = self.season_start()
        if start is None:
            return ChartOut(managers=managers, rows=[])
        first = analytics.market_value_day(start)
        today = analytics.market_value_day(datetime.now(UTC))
        events = analytics.transfer_events(self._transfer_records())
        squad = self._squad()
        involved = set(squad) | {e.player_id for e in events}
        histories = self._histories(list(involved))
        rows = {day: {"date": analytics.day_to_date(day).isoformat()} for day in range(first, today + 1)}
        for manager in managers:
            own_events = sorted((e for e in events if e.manager == manager.id), key=lambda e: e.date)
            held = {pid for pid, entry in squad.items() if entry.manager_id == manager.id}
            start_money = self.season.start_money
            if start_money is None:
                start_money = analytics.DEFAULT_START_MONEY
            cash = analytics.estimate_balance(manager.id, own_events, start_money)
            pending = list(own_events)
            for day in range(today, first - 1, -1):
                while pending and analytics.market_value_day(pending[-1].date) >= day:
                    event = pending.pop()
                    if event.kind == "buy":
                        held.discard(event.player_id)
                        cash += event.price
                    else:
                        held.add(event.player_id)
                        cash -= event.price
                values = [analytics.value_on_day(histories.get(pid) or [], day) for pid in held]
                rows[day][manager.id] = cash + sum(values) if all(v is not None for v in values) else None
        return ChartOut(managers=managers, rows=list(rows.values()))

    def matchday_charts(self) -> MatchdayChartsOut:
        managers = self._chart_managers()
        rankings = self.session.exec(
            select(MatchdayRanking)
            .where(MatchdayRanking.league_id == self.league_id)
            .order_by(MatchdayRanking.day)
        ).all()
        by_day: dict[int, list[MatchdayRanking]] = {}
        for ranking in rankings:
            by_day.setdefault(ranking.day, []).append(ranking)

        def rows(attribute: str) -> list[dict]:
            return [
                {"day": day, **{r.manager_id: getattr(r, attribute) for r in entries}}
                for day, entries in sorted(by_day.items())
            ]

        return MatchdayChartsOut(
            managers=managers,
            team_values=rows("team_value"),
            points=rows("points"),
            placements=rows("placement"),
        )

    def fixtures(self, day: int | None) -> FixturesOut:
        current = self.league.current_day
        wanted = day or current
        matches = self.session.exec(
            select(Fixture)
            .where(Fixture.competition_id == self.league.competition_id, Fixture.day == wanted)
            .order_by(Fixture.kickoff, Fixture.id)
        ).all()
        return FixturesOut(
            day=wanted,
            current_day=current,
            number_of_days=self.league.number_of_days,
            matches=[MatchOut.model_validate(m) for m in matches],
        )
