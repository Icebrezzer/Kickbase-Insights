"""The autotrader: bids and sells at Kickbase on its own, per league the user switched it on.

Every automation round (see `sync.automation`) it reads the live market, the squad, the saved lineup
and the budget, settles its earlier bids and paper trades (that is what it learns from), plans and then
acts. In a dry run (`trader_live` off) nothing is sent to Kickbase: the plan is logged and pushed.

Safeguards, besides the ones in `core.trader`:
- the server switch KBI_AUTOMATION__TRADER and the per league switch,
- the budget minus a reserve never goes below zero through its bids: open bids count as spent,
- one sale at most per round, only right before the auction it makes room for, and that bid is placed
  high enough to have a good chance,
- daily limits of bids and sales, no rebuy of a player it sold within a week,
- starters stay from shortly before the first kick-off until 5 minutes after it; without the automatic
  lineup they are not sold between matchdays at all,
- the profit trading pauses for the rest of the week after a realized loss of `stop_loss`,
- a negative budget shortly before the deadline is fixed by the sales that cost the fewest points.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from sqlmodel import Session, delete, select

from api.context import load_context
from core import analytics, coach
from core import trader as t
from db.models import (
    AutomationEvent,
    League,
    MarketValueHistory,
    ModelState,
    Player,
    ShadowTrade,
    SquadEntry,
    TradeLog,
    Transfer,
    UserAutomation,
    UserLeague,
    utcnow,
)
from kickbase import KickbaseAuthError, KickbaseClient, KickbaseError
from kickbase import models as kb
from sync.learning import load_state
from sync.learning import sell_ratio as learned_sell_ratio

if TYPE_CHECKING:
    from sync.automation import AutomationService

log = logging.getLogger(__name__)

### Kickbase's instant sale price is unknown before the sale: without a learned ratio count on this share
SAFE_SELL_RATIO = 0.9
### A negative budget is fixed this long before the deadline
RESCUE_BEFORE = timedelta(minutes=60)
### Paper purchases started per round and league, the most promising first
SHADOWS_PER_ROUND = 5
SHADOW_KEEP = timedelta(days=120)
STATE_KEY = "trader"


@dataclass(frozen=True)
class Action:
    kind: str # bid or sell
    purpose: str # lineup, cover, profit; sales: room, rescue, turn
    player_id: str
    name: str
    price: int # The bid, or the expected sale value
    market_value: int
    points_gain: float = 0
    reason: str = ""
    forecast_gain: int = 0 # Unscaled forecast over the holding time, for the forecast check later


class TraderService:
    def __init__(self, automation: AutomationService):
        self.automation = automation
        self.engine = automation.engine
        self.settings = automation.settings

    ### ==============================================================================================
    ### Round
    ### ==============================================================================================

    async def round(self, league: League, row: UserAutomation, client: KickbaseClient, now: datetime) -> list[Action]:
        if not self.settings.automation.trader or not row.trader:
            return []
        squad, budget, market = await asyncio.gather(
            client.manager_squad(league.id, row.user_id), client.own_budget(league.id), client.market(league.id)
        )
        if budget.budget is None:
            return []
        saved = await self._saved_lineup(league, client)
        await asyncio.to_thread(self._settle, league, row.user_id, squad, market, now)
        await asyncio.to_thread(self._settle_shadows, league, market, now)
        actions, shadows = await asyncio.to_thread(self._plan, league, row, squad, budget.budget, market, now, saved)
        if t.Options.load(row.trader_options).shadow:
            await asyncio.to_thread(self._start_shadows, league.id, shadows)
        for action in actions:
            if row.trader_live:
                try:
                    await self._execute(league, row.user_id, client, action)
                except KickbaseAuthError:
                    raise
                except KickbaseError as e:
                    self.automation.record(
                        row.user_id, league.id, "trader", f"{action.name}: {_verb(action)} fehlgeschlagen – {e}", ok=False
                    )
                    break # The plan assumed this step, the rest waits for the next round
            else:
                await asyncio.to_thread(self._log_planned, league, row.user_id, action, now)
        sales = [_shadow_sale(a) for a in actions if a.kind == "sell"]
        if sales:
            await asyncio.to_thread(self._start_shadows, league.id, sales)
        return actions

    async def _saved_lineup(self, league: League, client: KickbaseClient) -> list[str]:
        from sync.automation import parse_lineup

        try:
            return parse_lineup(await client.lineup(league.id))[1]
        except KickbaseAuthError:
            raise
        except KickbaseError as e:
            log.info("Saved lineup not read, the best eleven stands in for it: %s", e)
            return []

    async def _execute(self, league: League, user_id: str, client: KickbaseClient, action: Action) -> None:
        if action.kind == "sell":
            await self.automation.sell(league, user_id, client, action.player_id)
            received = await asyncio.to_thread(self._received, user_id, league.id, action.player_id) or action.price
            await asyncio.to_thread(self._log_sale, league, user_id, action, received)
            message = f"{action.name} verkauft ({action.reason}) für {received / 1e6:.2f} Mio. €"
        else:
            await client.place_offer(league.id, action.player_id, action.price)
            await asyncio.to_thread(self._log_bid, league, user_id, action, "open")
            message = f"Gebot {action.price / 1e6:.2f} Mio. € für {action.name} ({action.reason})"
        self.automation.record(user_id, league.id, "trader", message, details={"player_id": action.player_id, "purpose": action.purpose})
        await self.automation.push.send(user_id, "Autotrader", message, "/automatik", tag=f"trader-{league.id}")

    ### ==============================================================================================
    ### Settling the own bids, and learning from them
    ### ==============================================================================================

    def _settle(self, league: League, user_id: str, squad: kb.ManagerSquad, market: kb.Market, now: datetime) -> None:
        listed = {p.id: p for p in market.players}
        owned = {p.id: p for p in squad.players}
        with Session(self.engine) as session:
            rows = session.exec(
                select(TradeLog).where(
                    TradeLog.user_id == user_id, TradeLog.league_id == league.id, TradeLog.kind == "bid", TradeLog.status == "open"
                )
            ).all()
            if not rows:
                return
            state = t.Learned.load(load_state(session, STATE_KEY))
            for entry in rows:
                if entry.player_id in listed:
                    if listed[entry.player_id].own_bid(user_id) is None:
                        entry.status = "expired" # Withdrawn by hand
                        entry.resolved_at = now
                        session.add(entry)
                    continue
                if entry.player_id in owned:
                    entry.status = "won"
                    entry.paid = owned[entry.player_id].purchase_price or entry.price
                    state = t.after_auction(state, entry.market_value, True, entry.price, None)
                else:
                    sale = self._transfer_after(session, league.id, entry.player_id, entry.at)
                    if sale is not None and sale.buyer_id != user_id:
                        entry.status = "lost"
                        entry.details = {**entry.details, "winner_id": sale.buyer_id, "winner_price": sale.price}
                        state = t.after_auction(state, entry.market_value, False, entry.price, sale.price)
                    elif now - entry.at > timedelta(days=1):
                        entry.status = "expired" # Gone without a transfer the sync saw
                    else:
                        continue # The sync has not stored the transfer yet
                entry.resolved_at = now
                session.add(entry)
            self._save_state(session, state)
            session.commit()

    @staticmethod
    def _transfer_after(session: Session, league_id: str, player_id: str, since: datetime) -> Transfer | None:
        return session.exec(
            select(Transfer)
            .where(Transfer.league_id == league_id, Transfer.player_id == player_id, Transfer.date >= since - timedelta(hours=1))
            .order_by(Transfer.date)
        ).first()

    def _save_state(self, session: Session, state: t.Learned) -> None:
        row = session.get(ModelState, STATE_KEY) or ModelState(key=STATE_KEY)
        row.data = state.dump()
        row.updated_at = utcnow()
        session.add(row)

    ### ==============================================================================================
    ### Shadow trades
    ### ==============================================================================================

    def _start_shadows(self, league_id: str, shadows: list[ShadowTrade]) -> None:
        """One open paper trade per player and kind, so the same listing is not counted twice."""
        if not shadows:
            return
        with Session(self.engine) as session:
            open_keys = set(
                session.exec(
                    select(ShadowTrade.player_id, ShadowTrade.kind).where(
                        ShadowTrade.league_id == league_id, ShadowTrade.status.in_(["watching", "holding"])
                    )
                ).all()
            )
            for shadow in shadows:
                if (shadow.player_id, shadow.kind) not in open_keys:
                    shadow.league_id = league_id
                    session.add(shadow)
                    open_keys.add((shadow.player_id, shadow.kind))
            session.commit()

    def _settle_shadows(self, league: League, market: kb.Market, now: datetime) -> None:
        """Paper purchases: would the bid have won (the transfer shows the winner's price), and what
        was the player worth PROFIT_HOLD updates later. Paper sales: how the player moved afterwards."""
        listed = {p.id for p in market.players}
        with Session(self.engine) as session:
            session.exec(delete(ShadowTrade).where(ShadowTrade.resolved_at < now - SHADOW_KEEP))
            rows = session.exec(
                select(ShadowTrade).where(ShadowTrade.league_id == league.id, ShadowTrade.status.in_(["watching", "holding"]))
            ).all()
            if not rows:
                session.commit()
                return
            histories = dict(
                session.exec(
                    select(MarketValueHistory.player_id, MarketValueHistory.points).where(
                        MarketValueHistory.player_id.in_([r.player_id for r in rows])
                    )
                ).all()
            )
            state = t.Learned.load(load_state(session, STATE_KEY))
            ratio = learned_sell_ratio(session) or SAFE_SELL_RATIO
            for s in rows:
                points = histories.get(s.player_id) or []
                last_day = points[-1][0] if points else None
                if s.kind == "sell":
                    due = analytics.market_value_day(s.at) + t.REGRET_DAYS
                    if last_day is None or last_day < due:
                        continue
                    s.value_after = analytics.value_on_day(points, due) or points[-1][1]
                    s.result = s.value_after - s.market_value
                    state = t.after_regret(state, s.result)
                    s.status = "done"
                elif s.status == "watching":
                    if s.player_id in listed:
                        continue
                    sale = self._transfer_after(session, league.id, s.player_id, s.at)
                    if sale is not None:
                        won = sale.price <= s.bid
                        state = t.after_auction(state, s.market_value, won, s.bid, sale.price, t.SHADOW_WEIGHT)
                        s.winner_price = sale.price
                        if won:
                            s.status, s.paid, s.won_day = "holding", s.bid, analytics.market_value_day(sale.date)
                        else:
                            s.status = "lost"
                    elif s.free_agent and now - s.at > timedelta(days=1):
                        ### Kickbase's listing went without a buyer: the bid, at least the value, would have won
                        state = t.after_auction(state, s.market_value, True, s.bid, None, t.SHADOW_WEIGHT)
                        s.status, s.paid, s.won_day = "holding", s.bid, analytics.market_value_day(s.at)
                    elif now - s.at > timedelta(days=2):
                        s.status = "expired"
                    else:
                        continue
                else: # holding
                    due = (s.won_day or 0) + t.PROFIT_HOLD
                    if last_day is None or last_day < due:
                        continue
                    s.value_after = analytics.value_on_day(points, due) or points[-1][1]
                    s.result = int(s.value_after * ratio) - (s.paid or s.bid)
                    state = t.after_forecast(state, s.forecast_gain, s.value_after - s.market_value)
                    if s.purpose == "profit":
                        state = t.after_sale(state, s.result, t.SHADOW_WEIGHT)
                    s.status = "done"
                s.resolved_at = now if s.status in ("done", "lost", "expired") else None
                session.add(s)
            self._save_state(session, state)
            session.commit()

    ### ==============================================================================================
    ### Planning
    ### ==============================================================================================

    def _plan(
        self,
        league: League,
        row: UserAutomation,
        squad: kb.ManagerSquad,
        budget: int,
        market: kb.Market,
        now: datetime,
        saved: list[str] | None = None,
    ) -> tuple[list[Action], list[ShadowTrade]]:
        from api.insights import Insights
        from api.routes import analysis_limits

        opts = t.Options.load(row.trader_options)
        min_play = opts.min_play / 100
        user_id = row.user_id
        own_ids = [p.id for p in squad.players]
        listed = {p.id: p for p in market.players}
        with Session(self.engine) as session:
            membership = session.get(UserLeague, (user_id, league.id))
            max_squad, max_club = analysis_limits(self.settings, membership)
            context = load_context(session, league.competition_id, [*own_ids, *listed], now)
            histories = dict(
                session.exec(
                    select(MarketValueHistory.player_id, MarketValueHistory.points).where(
                        MarketValueHistory.player_id.in_([*own_ids, *listed])
                    )
                ).all()
            )
            offers = {
                o.id: o
                for o in Insights(session, league, user_id, self.automation.model, max_squad, max_club).market()
                if o.id in listed
            }
            state = t.Learned.load(load_state(session, STATE_KEY))
            ratio = learned_sell_ratio(session) or SAFE_SELL_RATIO
            history = self._trades(session, user_id, league.id)

        local = now.astimezone(analytics.MARKET_VALUE_TIMEZONE)
        midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
        today = [h for h in history if h.at >= midnight]
        bids_left = opts.daily_bids - sum(1 for h in today if h.kind == "bid")
        sales_left = opts.daily_sales - sum(1 for h in today if h.kind == "sell")
        sold_recently = {h.player_id for h in history if h.kind == "sell" and now - h.at < t.REBUY_BLOCK}
        bought = {h.player_id: h for h in history if h.kind == "bid" and h.status == "won"}
        week = t.week_of(now)
        week_profit = sum(h.profit or 0 for h in history if h.kind == "sell" and t.week_of(h.at) == week)
        paused = opts.stop_loss > 0 and week_profit < -opts.stop_loss
        scale = state.gain_scale
        raw_gain: dict[str, int] = {}

        def candidate(pid: str, position: int, status: int, team_id: str | None, average: int | None, value: int) -> t.Candidate:
            e = context.expectation(pid, position, status, team_id, average)
            points = histories.get(pid) or []
            prediction = coach.forecast(points, self.automation.model, t.PROFIT_HOLD, context.match_points(pid))
            raw_gain[pid] = prediction.projection[-1] if prediction else 0
            return t.Candidate(
                player_id=pid,
                position=position,
                expected=e.expected,
                average=e.season_average,
                form=e.form,
                play=e.play_probability,
                fit=status in coach.STATUS_AVAILABILITY,
                today=(analytics.market_value_deltas(points).get("today") or 0) if points else 0,
                forecast=prediction.next_change if prediction else 0,
                gain=int(raw_gain[pid] * scale),
                value=value,
                team_id=team_id,
            )

        ### Starters: kept around the kick-off; without the automatic lineup also between matchdays,
        ### because nobody would fill the gap
        live = coach.live_matchday(context.fixtures, now) is not None
        keep_starters = t.starters_locked(context.fixtures, now, opts.starter_lock) or (not live and not row.auto_lineup)
        own = []
        for p in squad.players:
            own.append(candidate(p.id, p.position, p.status, p.team_id, p.average_points, p.market_value))
        own = _with_best(own)
        starters = set(saved or []) or {c.player_id for c in own if c.in_best}
        locked_own = []
        for c in own:
            held = bought.get(c.player_id)
            fresh = held is not None and c.fit and now - (held.resolved_at or held.at) < t.MIN_HOLD
            locked_own.append(replace(c, locked=fresh or (keep_starters and c.player_id in starters)))
        own = locked_own
        names = {p.id: p.last_name for p in squad.players} | {p.id: p.last_name for p in market.players}
        actions: list[Action] = []

        ### A negative budget shortly before the deadline costs the whole matchday
        upcoming = context.upcoming
        if budget < 0 and upcoming is not None and timedelta(0) < upcoming.deadline - now <= RESCUE_BEFORE:
            plan = coach.rescue_sales(
                budget,
                [coach.SellCandidate(c.player_id, c.position, c.expected, int(c.value * ratio)) for c in own],
                protected=[c.player_id for c in own if c.locked and c.fit],
            )
            by_id = {c.player_id: c for c in own}
            return [
                Action("sell", "rescue", pid, names.get(pid, pid), int(by_id[pid].value * ratio), by_id[pid].value, reason="Budget im Minus vor der Deadline")
                for pid in plan.sales
            ], []

        ### A profit purchase whose forecast turned is sold in the evening, before the update at 22:00
        if sales_left > 0 and self.settings.automation.sell_advice_hour <= local.hour < 22:
            for c in own:
                held = bought.get(c.player_id)
                if held and held.purpose == "profit" and not c.locked and not c.in_best and c.forecast < 0:
                    actions.append(
                        Action("sell", "turn", c.player_id, names.get(c.player_id, c.player_id), int(c.value * ratio), c.value, reason="Prognose dreht ins Minus")
                    )
                    own = _with_best([o for o in own if o.player_id != c.player_id])
                    sales_left -= 1
                    break

        ### Targets
        open_bids = {pid: bid for pid, p in listed.items() if (bid := p.own_bid(user_id)) is not None}
        free = budget - opts.reserve - sum(open_bids.values()) + sum(a.price for a in actions)
        slots = max_squad - len(own) - len(open_bids)
        market_candidates: list[t.Candidate] = []
        for pid, p in listed.items():
            offer = offers.get(pid)
            seller = p.seller.id if p.seller else None
            if offer is None or seller == user_id or pid in open_bids or pid in sold_recently or offer.own_club_full:
                continue
            c = candidate(pid, p.position, p.status, p.team_id, p.average_points, p.market_value)
            market_candidates.append(
                replace(c, price=p.price or p.market_value, bid_low=offer.bid_low or 0, bid_high=offer.bid_high or 0, expires_at=offer.expires_at)
            )
        free_agents = {pid for pid, p in listed.items() if p.seller is None}

        options: list[tuple[float, str, t.Candidate, t.Upgrade | None]] = []
        for c in market_candidates:
            upgrade = t.lineup_upgrade(own, c, opts)
            if upgrade is not None:
                options.append((1e9 + upgrade.gain, "lineup", c, upgrade))
            elif row.trader_profit and not paused and c.fit and c.forecast > 0:
                options.append((float(t.profit_margin(c, c.bid_low or c.value)), "profit", c, None))
        cover = t.cover_target(own, [c for c in market_candidates if not any(o[2] is c for o in options if o[1] == "lineup")], opts)
        if cover is not None:
            options.append((1e8, "cover", cover, None))
        options.sort(key=lambda o: -o[0])

        shadows: list[ShadowTrade] = []
        sold_now = any(a.kind == "sell" for a in actions)
        bid_on: set[str] = set()
        for _, purpose, c, upgrade in options:
            if c.player_id in bid_on:
                continue
            profit = purpose == "profit"
            extra = state.extra[coach.price_class(c.value)]
            if profit and len(shadows) < SHADOWS_PER_ROUND:
                ### On paper at the realistic bid. "near": the rules would have passed on it. Only
                ### "profit" ones move the minimum margin, the rejected ones would bias it upwards
                paper = t.bid_for(c, extra, None, False)
                if paper is not None:
                    rule_bid = t.bid_for(c, extra, None, True)
                    qualified = rule_bid is not None and t.is_profit_buy(c, rule_bid, state.min_margin)
                    shadows.append(
                        _shadow_buy(c, rule_bid if qualified else paper, raw_gain.get(c.player_id, 0),
                                    "profit" if qualified else "near", c.player_id in free_agents)
                    )
            if bids_left <= 0:
                continue
            bid = _price(c, purpose, upgrade, extra, free, opts, state) if slots > 0 else None
            sale = None
            if bid is None:
                ### Room or money is only made right before the auction ends, one sale per round
                if purpose == "cover" or sold_now or sales_left <= 0 or c.expires_at is None:
                    continue
                if c.expires_at - now > timedelta(minutes=opts.sell_window):
                    continue
                sale = t.pick_sale(_with_best([*own, replace(c, locked=True)]), c, min_play, state.swap_edge, upgrade.replaced if upgrade else None)
                if sale is None:
                    continue
                proceeds = int(sale.value * ratio)
                ### A player is given up for this one: bid high enough to have a good chance
                bid = _price(c, purpose, upgrade, max(extra, t.ROOM_EXTRA), free + proceeds, opts, state)
                if bid is None:
                    continue
                reason = (
                    "verletzt/fällt aus" if not sale.fit
                    else "kein Stammspieler" if not sale.regular(min_play)
                    else f"Platz für {names.get(c.player_id)}"
                )
                actions.append(Action("sell", "room", sale.player_id, names.get(sale.player_id, sale.player_id), proceeds, sale.value, reason=reason))
                own = [o for o in own if o.player_id != sale.player_id]
                free += proceeds
                slots += 1
                sales_left -= 1
                sold_now = True
            if upgrade is not None:
                reason = f"+{upgrade.gain:.0f} erw. Punkte in der Elf, {t.cost_per_point(upgrade, bid) / 1e3:.0f} Tsd. € je Punkt"
            elif purpose == "cover":
                reason = f"Ersatz für Position {c.position}"
            else:
                reason = f"Prognose {c.gain / 1e3:+.0f} Tsd. in {t.PROFIT_HOLD} Tagen"
            actions.append(
                Action("bid", purpose, c.player_id, names.get(c.player_id, c.player_id), bid, c.value,
                       upgrade.gain if upgrade else 0, reason, raw_gain.get(c.player_id, 0))
            )
            bid_on.add(c.player_id)
            own = _with_best([*own, c])
            free -= bid
            slots -= 1
            bids_left -= 1
        ### Paper trades only for what was not bought for real
        shadows = [s for s in shadows if s.player_id not in bid_on]
        return actions, shadows

    ### ==============================================================================================
    ### Log
    ### ==============================================================================================

    def _trades(self, session: Session, user_id: str, league_id: str) -> list[TradeLog]:
        since = utcnow() - timedelta(days=60)
        return list(
            session.exec(
                select(TradeLog).where(TradeLog.user_id == user_id, TradeLog.league_id == league_id, TradeLog.at >= since)
            )
        )

    def _log_bid(self, league: League, user_id: str, action: Action, status: str) -> None:
        with Session(self.engine) as session:
            session.add(
                TradeLog(
                    user_id=user_id,
                    league_id=league.id,
                    player_id=action.player_id,
                    kind=action.kind,
                    purpose=action.purpose,
                    status=status,
                    price=action.price,
                    market_value=action.market_value,
                    points_gain=action.points_gain,
                    details={"reason": action.reason, "name": action.name, "forecast_gain": action.forecast_gain},
                )
            )
            session.commit()

    def _received(self, user_id: str, league_id: str, player_id: str) -> int | None:
        with Session(self.engine) as session:
            event = session.exec(
                select(AutomationEvent)
                .where(AutomationEvent.user_id == user_id, AutomationEvent.league_id == league_id, AutomationEvent.kind == "sell")
                .order_by(AutomationEvent.at.desc())
            ).first()
        if event is None or event.details.get("player_id") != player_id:
            return None
        return event.details.get("received")

    def _log_sale(self, league: League, user_id: str, action: Action, received: int) -> None:
        with Session(self.engine) as session:
            bought = session.exec(
                select(TradeLog)
                .where(
                    TradeLog.user_id == user_id,
                    TradeLog.league_id == league.id,
                    TradeLog.player_id == action.player_id,
                    TradeLog.kind == "bid",
                    TradeLog.status == "won",
                )
                .order_by(TradeLog.at.desc())
            ).first()
            cost = bought.paid if bought and bought.paid else None
            if cost is None:
                entry = session.get(SquadEntry, (league.id, action.player_id))
                cost = entry.purchase_price if entry else None
            profit = received - cost if cost is not None else None
            session.add(
                TradeLog(
                    user_id=user_id,
                    league_id=league.id,
                    player_id=action.player_id,
                    kind="sell",
                    purpose=action.purpose,
                    status="sold",
                    price=received,
                    market_value=action.market_value,
                    profit=profit,
                    resolved_at=utcnow(),
                    details={"reason": action.reason, "name": action.name},
                )
            )
            if bought is not None and bought.purpose == "profit" and profit is not None:
                state = t.Learned.load(load_state(session, STATE_KEY))
                state = t.after_sale(state, profit)
                forecast = int(bought.details.get("forecast_gain") or 0)
                state = t.after_forecast(state, forecast, action.market_value - bought.market_value)
                self._save_state(session, state)
            session.commit()

    def _log_planned(self, league: League, user_id: str, action: Action, now: datetime) -> None:
        """Dry run: logged and pushed once per player, kind and day."""
        key = f"trader:{league.id}:{user_id}:{action.kind}:{action.player_id}:{now.astimezone(analytics.MARKET_VALUE_TIMEZONE).date()}"
        if self.automation._has_key(key):
            return
        self._log_bid(league, user_id, action, "planned")
        message = f"Probelauf: würde {action.name} {_verb(action)} – {action.reason}"
        self.automation.record(user_id, league.id, "trader", message, key=key, details={"player_id": action.player_id, "price": action.price})

    ### ==============================================================================================
    ### Statistics
    ### ==============================================================================================

    def view(self, user_id: str, league_id: str) -> dict:
        with Session(self.engine) as session:
            rows = list(
                session.exec(
                    select(TradeLog)
                    .where(TradeLog.user_id == user_id, TradeLog.league_id == league_id)
                    .order_by(TradeLog.at.desc())
                )
            )
            shadows = list(
                session.exec(select(ShadowTrade).where(ShadowTrade.league_id == league_id).order_by(ShadowTrade.at.desc()))
            )
            names = dict(
                session.exec(select(Player.id, Player.last_name).where(Player.id.in_([s.player_id for s in shadows[:30]]))).all()
            )
            state = t.Learned.load(load_state(session, STATE_KEY))
        trades = [t.Trade(r.at, r.kind, r.status, r.price, r.paid, r.profit, r.points_gain) for r in rows]
        trades += [t.Trade(s.resolved_at or s.at, "shadow", s.status, s.bid, s.paid, s.result) for s in shadows if s.kind == "buy"]
        weeks = t.weekly(trades)
        week = t.week_of(utcnow())
        current = next((w for w in weeks if w["week"] == week), None)
        with Session(self.engine) as session:
            row = session.get(UserAutomation, (user_id, league_id))
        opts = t.Options.load(row.trader_options if row else None)
        done = [s for s in shadows if s.kind == "buy" and s.status == "done"]
        regrets = [s.result for s in shadows if s.kind == "sell" and s.status == "done" and s.result is not None]
        return {
            "weeks": weeks[:12],
            "trades": [
                {
                    "id": r.id,
                    "at": r.at,
                    "player_id": r.player_id,
                    "name": r.details.get("name"),
                    "kind": r.kind,
                    "purpose": r.purpose,
                    "status": r.status,
                    "price": r.price,
                    "market_value": r.market_value,
                    "paid": r.paid,
                    "profit": r.profit,
                    "points_gain": r.points_gain,
                    "reason": r.details.get("reason"),
                }
                for r in rows[:40]
            ],
            "shadows": [
                {
                    "id": s.id,
                    "at": s.at,
                    "player_id": s.player_id,
                    "name": names.get(s.player_id),
                    "kind": s.kind,
                    "purpose": s.purpose,
                    "status": s.status,
                    "bid": s.bid,
                    "market_value": s.market_value,
                    "winner_price": s.winner_price,
                    "value_after": s.value_after,
                    "result": s.result,
                }
                for s in shadows[:30]
            ],
            "shadow_summary": {
                "open": sum(1 for s in shadows if s.status in ("watching", "holding")),
                "done": len(done),
                "profit": sum(s.result or 0 for s in done),
                "hit_rate": sum(1 for s in done if (s.result or 0) > 0) / len(done) if done else None,
                "sold_then_rose": sum(1 for r in regrets if r > 100_000) / len(regrets) if regrets else None,
            },
            "learned": {
                "extra": list(state.extra),
                "min_margin": state.min_margin,
                "won": state.won,
                "lost": state.lost,
                "shadow_won": state.shadow_won,
                "shadow_lost": state.shadow_lost,
                "gain_scale": state.gain_scale,
                "gain_samples": state.gain_samples,
                "swap_edge": state.swap_edge,
                "regret_samples": state.regret_samples,
            },
            "paused": bool(current and opts.stop_loss > 0 and current["profit"] < -opts.stop_loss),
            "enabled_on_server": self.settings.automation.trader,
        }


def _price(
    c: t.Candidate, purpose: str, upgrade: t.Upgrade | None, extra: float, money: int, opts: t.Options, state: t.Learned
) -> int | None:
    """The bid for `c` with `money` free, or None when it does not fit or is not worth it."""
    profit = purpose == "profit"
    cap = int(money * (opts.profit_share if profit else opts.lineup_share) / 100)
    if purpose == "cover":
        cap = min(cap, opts.cover_max_price)
    bid = t.bid_for(c, extra, cap, profit)
    if bid is None:
        return None
    if profit and not t.is_profit_buy(c, bid, state.min_margin):
        return None
    if upgrade is not None and not t.worth_it(upgrade, bid, opts):
        ### The fair price: the lowest sensible bid, if that is still worth it
        low = t.bid_for(c, 0.0, cap, False)
        return low if low is not None and t.worth_it(upgrade, low, opts) else None
    return bid


def _with_best(squad: list[t.Candidate]) -> list[t.Candidate]:
    best = set(t.best_of(squad).player_ids) if squad else set()
    return [replace(c, in_best=c.player_id in best) for c in squad]


def _shadow_buy(c: t.Candidate, bid: int, forecast_gain: int, purpose: str, free_agent: bool) -> ShadowTrade:
    return ShadowTrade(
        league_id="",
        player_id=c.player_id,
        kind="buy",
        purpose=purpose,
        bid=bid,
        market_value=c.value,
        forecast_gain=forecast_gain,
        free_agent=free_agent,
    )


def _shadow_sale(action: Action) -> ShadowTrade:
    return ShadowTrade(league_id="", player_id=action.player_id, kind="sell", purpose=action.purpose, market_value=action.market_value)


def _verb(action: Action) -> str:
    return f"für {action.price / 1e6:.2f} Mio. € bieten" if action.kind == "bid" else "verkaufen"
