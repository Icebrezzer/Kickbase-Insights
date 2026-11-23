"""Builds the API responses from the database.

Everything here only reads. The results only change when a sync finishes, so the API caches them
per league, viewer and sync timestamp (see `api.routes`). The viewer matters for what only they may
see: their real budget and their own bids.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from statistics import median

from sqlmodel import Session, select

from api.context import load_context
from api.schemas import (
    BattleEntryOut,
    BattleOut,
    BidAdviceOut,
    ChartManager,
    ChartOut,
    FairCurvePointOut,
    FairPlayerOut,
    FairValuesOut,
    FixturesOut,
    ManagerOut,
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
    BalancePointOut,
    BuyOptionOut,
    LostAuctionOut,
    TeamOut,
    TransferOut,
    TurnoverOut,
    WatchedPlayerOut,
)
from core import analytics, coach
from db.models import (
    BidHistory,
    Battle,
    BattleEntry,
    Fixture,
    League,
    LeagueSeason,
    Manager,
    MarketBid,
    MarketListing,
    MarketValueHistory,
    MatchdayRanking,
    Player,
    PlayerForm,
    SquadEntry,
    Team,
    Transfer,
    UserLeague,
)
from kickbase.models import ScoutedPlayer


class Insights:
    def __init__(
        self,
        session: Session,
        league: League,
        viewer_id: str | None = None,
        model: coach.ForecastModel | None = None,
        max_squad: int = 18,
    ):
        self.session = session
        self.league = league
        self.league_id = league.id
        self.viewer_id = viewer_id
        self.model = model or coach.ForecastModel()
        self.max_squad = max_squad
        self._match_points: dict[str, list[tuple[int, int]]] | None = None
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

    def balances(self) -> dict[str, tuple[int, int]]:
        """Per manager the balance and the highest possible bid. The viewer's own come from the real
        budget, the others are estimates from the start money and the transfers."""
        events = analytics.transfer_events(self._transfer_records())
        start_money = self.season.start_money or analytics.DEFAULT_START_MONEY
        own_budget = self.own_budget()
        result = {}
        for manager in self._managers():
            estimated = analytics.estimate_balance(manager.id, events, start_money)
            balance = own_budget if manager.id == self.viewer_id and own_budget is not None else estimated
            result[manager.id] = (balance, analytics.max_bid(balance, manager.team_value or 0))
        return result

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
        records = self._transfer_records()
        histories = self._histories(list({t.player_id for t in records}))
        return analytics.kickbase_purchases(records, lambda player_id: histories.get(player_id) or [])

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
        for manager in self._managers():
            own = [p for p in purchases if p.transfer.buyer == manager.id]
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
        league_shares = [p.overpay_share for p in rival_purchases]
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
                    clubs.can_buy(mid, player.team_id),
                    money[mid][1] if balances and mid in money else None,
                    league_shares,
                )
                if estimate.probability > 0:
                    estimates.append(estimate)
            estimates.sort(key=lambda e: -e.probability)
            matches = context.match_points(player.id)
            prediction = coach.forecast(histories.get(player.id) or [], self.model, max(updates, 1), matches)
            gain = prediction.projection[updates - 1] if prediction and updates > 0 else None
            margin = None if gain is None else gain - max(price - player.market_value, 0)
            bids = coach.bid_range(player.market_value, price, league_shares, estimates, gain, own_max_bid)
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
                    own_club_full=own_club >= coach.MAX_PER_CLUB,
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
        start_money = self.season.start_money or analytics.DEFAULT_START_MONEY
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
                    blocked_clubs=[team for team, count in clubs.counts.get(manager.id, Counter()).items() if count >= coach.MAX_PER_CLUB],
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
                blocked = "3 Spieler vom Verein"
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
        start_money = self.season.start_money or analytics.DEFAULT_START_MONEY
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
            estimated = analytics.estimate_balance(manager.id, own_events, start_money)
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
