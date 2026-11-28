"""The autotrader: bids and sells at Kickbase on its own, per league the user switched it on.

Every automation round (see `sync.automation`) it reads the live market, the squad, the saved lineup
and the budget, settles its earlier bids and paper trades (that is what it learns from), plans and then
acts. In a dry run (`trader_live` off) nothing is sent to Kickbase: the plan is logged and pushed.

Safeguards, besides the ones in `core.trader`:
- the server switch KBI_AUTOMATION__TRADER and the per league switch,
- bids stay within the balance minus a reserve plus a credit up to the max bid that the players outside
  the best eleven can pay back; open bids count as spent and as players to come,
- one sale at most per round, only right before the auction it makes room for, and that bid is placed
  high enough to have a good chance,
- daily limits of bids and sales, no rebuy of a player it sold within a week,
- starters stay from shortly before the first kick-off until 5 minutes after it; without the automatic
  lineup they are not sold between matchdays at all,
- the profit trading pauses for the rest of the week after a realized loss of `stop_loss`,
- a negative budget is fixed from the last market value update before the deadline on, by the sales
  that cost the fewest points.

Every round's decisions, with the reason for each market player, go to `TraderDebug` (only when they
changed), for the export that lets the parameters be tuned from outside.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import case, func, tuple_
from sqlmodel import Session, delete, select

from api.context import load_context
from core import analytics, coach, finance, flags, learning, risk
from core import reasons as rc
from core import shadow_intelligence as si
from core import trader as t
from db import exclusive
from db.models import (
    AutomationEvent,
    DecisionSnapshot,
    ForecastObservation,
    League,
    MarketValueHistory,
    ModelState,
    Player,
    ShadowTrade,
    TradeLog,
    TraderDebug,
    Transfer,
    UserAutomation,
    UserLeague,
    utcnow,
)
from kickbase import KickbaseAuthError, KickbaseClient, KickbaseError
from kickbase import models as kb
from sync import shadow_analysis, shadow_retention
from sync.learning import load_state
from sync.learning import sell_ratio as learned_sell_ratio
from sync.strategy import StrategyStore

if TYPE_CHECKING:
    from sync.automation import AutomationService

log = logging.getLogger(__name__)

### The instant sale ratio is the league option `sell_ratio` (t.sell_ratio): Kickbase pays the market value
### Forecast observations (E10.00) are kept this long, then only their statistics are gone too
FORECAST_KEEP_DAYS = 120
### Paper purchases started per round and league, the most promising first
SHADOWS_PER_ROUND = 5
SHADOW_KEEP = timedelta(days=120)
### Sales of profit positions ("turn" is the name before milestone 2); only these count for the stop-loss
EXIT_PURPOSES = ("exit", "turn")
EXIT_ORDER = ("SPORT", "STOP", "TRAIL", "TURN", "TAKE", "TIME")
### Debug rounds are kept this long
DEBUG_KEEP = timedelta(days=21)
### An unconfirmed call that Kickbase does not show after this long failed
RECONCILE_AFTER = timedelta(minutes=10)
### An unclear bid whose listing is gone and whose transfer never shows up is closed after this long
UNSETTLED_GIVE_UP = timedelta(days=2)
### This many failed Kickbase calls within an hour pause the live trading (dry run) for that hour
ERROR_PAUSE = 3

### Read first by whoever (or whatever AI) reviews an export
EXPORT_ABOUT = """Kickbase Insights autotrader export. Money in euro, times in UTC.
options: per league settings, limits in option_limits (min_play and min_avg_edge in percent, sell_window and
starter_lock in minutes, lineup_share in percent of the money per bid, profit_share in percent of team value plus
balance for all profit positions together, min_roi in percent net, credit_mode 0 none / 1 eleven / 2 also profit).
Net profit = (value + gain) x conservative sell ratio - bid. learned: the global base model; learned_league:
this league's own bid heights and auction counts; learned_effective: what this league trades with (blend).
Bids use P(win) from the league's won auctions (rounds[].league_auctions, market[].p_win_at_low) when there
are at least 8, maximizing P(win) x (worth - bid); else the learned extra. Fields of learned:
extra = how far up the bid range (0 = low, 1 = high) per price class, min_margin = euro a profit buy must
gain after the bid premium, gain_ratio = actual/forecast market value gain, swap_edge = euro per day a swap
target must rise more than the player sold. constants: fixed rules, a change needs a new build.
rounds: one entry per round whose decisions changed; market[].decision says why a player was bought or not,
money = what was available for that bid, credit = the overdraft used on top of cash_free.
risk_blocked lists actions the risk engine refused, with a reason code.
trades: bids (pending/unknown/open/won/lost/expired/failed), sales (sold, profit null when unknown), dry run (planned).
shadows: paper trades, result = euro the paper trade made (buy) or the value change after a real sale (sell).
To change parameters, upload JSON {"options": {...}, "learned": {...}} on the Automatik page (Import). Only
the given keys change, everything is clamped to its limits."""
STATE_KEY = "trader"


@dataclass(frozen=True)
class Action:
    kind: str # bid, sell or withdraw
    purpose: str # lineup, cover, profit; sales: room, rescue, turn
    player_id: str
    name: str
    price: int # The bid, or the expected sale value
    market_value: int
    points_gain: float = 0
    reason: str = ""
    forecast_gain: int = 0 # Unscaled forecast over the holding time, for the forecast check later
    cost: int | None = None # Sales: purchase price, read before the sale removes the squad entry
    for_player: str | None = None # Room sales: the auction the sale makes room for, checked again right before
    config_version: int | None = None # The strategy configuration the round planned with (E02.04)
    collateral: tuple = () # finance.Collateral: sales that pay this bid back once it is won (E04.04/E04.05)


class TraderService:
    def __init__(self, automation: AutomationService):
        ### Forecast observations already stored, per league and market value day, and the last day the
        ### open ones were settled: a round only writes players not seen today (E10.00)
        self._observed: dict[tuple[str, int], set[str]] = {}
        self._observations_settled: dict[str, int] = {}
        self._snapshots_pruned: dict[tuple[str, str], int] = {}
        ### Rejection statistics per league and user, with the newest debug row they were computed from
        self._rejections: dict[tuple[str, str], tuple[int, dict]] = {}
        ### Versioned strategy configuration per user and league (E02.03)
        self.configs = StrategyStore(automation.engine)
        self.automation = automation
        self.engine = automation.engine
        self.settings = automation.settings
        self._pushes: list[tuple[str, str, str, str]] = [] # Filled while planning in a thread, sent after
        self._last_debug: dict[tuple[str, str], str] = {}
        self._latest: dict[tuple[str, str], tuple[datetime, dict]] = {} # Latest round per league and user
        ### Learning is read, changed and written back: one at a time, so no round's update is lost
        self._learn = threading.Lock()
        self.after_trade = None # Wired by api.app to refresh private API data.

    @contextmanager
    def _learning(self) -> Iterator[None]:
        """Threads of this process and every other process on the same database (flock for SQLite,
        an advisory lock for PostgreSQL, see db.exclusive) learn one at a time."""
        with self._learn, exclusive(self.engine, "trader-learning"):
            yield

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
        ### The configuration of this round: loaded once, a change meanwhile counts from the next round
        config = await asyncio.to_thread(self.configs.options, row.user_id, league.id)
        opts = config[1]
        await asyncio.to_thread(self._settle, league, row.user_id, squad, market, now)
        await asyncio.to_thread(self._settle_shadows, league, market, now, opts.shadow)
        actions, shadows = await asyncio.to_thread(self._plan, league, row, squad, budget.budget, market, now, saved, config)
        if opts.shadow:
            await asyncio.to_thread(self._start_shadows, league.id, shadows, row.user_id)
        pause = await asyncio.to_thread(self._error_pause, league.id, row.user_id, now) if row.trader_live else None
        executed: list[Action] = []
        for action in actions:
            if not row.trader_live or pause:
                await asyncio.to_thread(self._log_planned, league, row.user_id, action, now)
                continue
            ### Switched off meanwhile (server, league or live switch): nothing more is sent
            current = await asyncio.to_thread(self.automation.get_settings, row.user_id, league.id)
            if not (self.settings.automation.trader and current.trader and current.trader_live):
                break
            if not await self._revalidate(league, current, client, action, config):
                break
            current = await asyncio.to_thread(self.automation.get_settings, row.user_id, league.id)
            if not (self.settings.automation.trader and current.trader and current.trader_live):
                break
            outcome = await self._execute(league, row.user_id, client, action)
            if outcome == "done":
                executed.append(action)
            if outcome in ("done", "unknown") and self.after_trade is not None:
                try:
                    await self.after_trade(league.id, row.user_id, client)
                except Exception:
                    log.exception("Private data refresh after trade failed")
            ### Anything unconfirmed, and every sale, ends the round: the next one re-plans with what
            ### Kickbase confirmed (balance, squad), so no step builds on an assumed result
            if outcome != "done" or action.kind == "sell":
                break
        ### Paper sales only follow sales Kickbase confirmed
        sales = [_shadow_sale(a) for a in executed if a.kind == "sell"]
        if sales and opts.shadow:
            await asyncio.to_thread(self._start_shadows, league.id, sales, row.user_id)
        while self._pushes:
            user_id, title, message, tag = self._pushes.pop()
            await self._push(user_id, title, message, tag)
        return executed if row.trader_live and not pause else actions

    async def _revalidate(self, league: League, row: UserAutomation, client: KickbaseClient, action: Action,
                          config: tuple[int, t.Options] | None = None) -> bool:
        """Re-plan on fresh account state; manual bids and elapsed deadlines can invalidate a plan."""
        squad, budget, market = await asyncio.gather(
            client.manager_squad(league.id, row.user_id), client.own_budget(league.id), client.market(league.id)
        )
        if budget.budget is None:
            return False
        saved = await self._saved_lineup(league, client)
        fresh, _ = await asyncio.to_thread(self._plan, league, row, squad, budget.budget, market, utcnow(), saved, config)
        if not fresh:
            return False
        first = fresh[0] # Later actions may depend on withdrawals or sales not executed yet.
        return (first.kind, first.purpose, first.player_id, first.price, first.for_player) == (
            action.kind, action.purpose, action.player_id, action.price, action.for_player
        )

    async def _push(self, user_id: str, title: str, message: str, tag: str) -> None:
        """A failed push is no failed trade: it never changes the outcome or repeats an action."""
        try:
            await self.automation.push.send(user_id, title, message, "/automatik", tag=tag)
        except Exception as e: # noqa: BLE001
            log.warning("Push not sent: %s", e)

    async def _saved_lineup(self, league: League, client: KickbaseClient) -> list[str] | None:
        """The lineup saved at Kickbase, None when it cannot be read: then no player counts as benched."""
        from sync.automation import parse_lineup

        try:
            ids = parse_lineup(await client.lineup(league.id))[1]
        except KickbaseAuthError:
            raise
        except KickbaseError as e:
            log.info("Saved lineup not read, every fit player counts as a starter: %s", e)
            return None
        return ids or None

    def _error_pause(self, league_id: str, user_id: str, now: datetime) -> str | None:
        """Repeated failed calls within the last hour: live trading pauses (dry run) until they age out."""
        with Session(self.engine) as session:
            failures = session.exec(
                select(AutomationEvent.details).where(
                    AutomationEvent.user_id == user_id, AutomationEvent.league_id == league_id, AutomationEvent.kind == "trader",
                    AutomationEvent.ok == False, AutomationEvent.at >= now - timedelta(hours=1),  # noqa: E712
                )
            ).all()
        failures = [d for d in failures if d.get("api_error") or d.get("status") in ("failed", "unknown")]
        if len(failures) < ERROR_PAUSE:
            return None
        reason = f"{len(failures)} fehlgeschlagene Kickbase-Aufrufe in der letzten Stunde – Live-Handel pausiert"
        key = f"trader-pause:{league_id}:{user_id}:{now.astimezone(analytics.MARKET_VALUE_TIMEZONE):%Y-%m-%d-%H}"
        if not self.automation._has_key(key):
            self.automation.record(user_id, league_id, "trader-pause", reason, ok=False, key=key)
            self._pushes.append((user_id, "Autotrader pausiert", reason, f"trader-pause-{league_id}"))
        return reason

    async def _execute(self, league: League, user_id: str, client: KickbaseClient, action: Action) -> str:
        """Runs one action. The intent is stored before Kickbase is called, so a lost answer or a crash
        leaves an `unknown` entry that the next round checks against Kickbase instead of sending again.
        Returns done, failed, unknown or skipped."""
        if action.kind == "withdraw":
            return await self._withdraw(league, user_id, client, action)
        before = None
        try:
            if action.kind == "sell":
                if action.for_player and not await self._still_open(league, client, action.for_player):
                    return "skipped" # The auction this sale made room for is over or gone
                before = (await client.own_budget(league.id)).budget
        except KickbaseAuthError:
            raise
        except KickbaseError as e:
            self.automation.record(user_id, league.id, "trader", f"{action.name}: Prüfung vor dem {_verb(action)} fehlgeschlagen – {e}", ok=False, details={"api_error": True})
            return "failed"
        entry_id = await asyncio.to_thread(self._log_intent, league, user_id, action)
        try:
            if action.kind == "sell":
                await client.sell_to_kickbase(league.id, action.player_id)
            else:
                await client.place_offer(league.id, action.player_id, action.price)
        except KickbaseError as e:
            ### A 4xx is a refusal. No answer or a server error may still have gone through
            status = "unknown" if e.status_code is None or e.status_code >= 500 else "failed"
            await asyncio.to_thread(self._finish_entry, entry_id, status, error=str(e))
            word = "unklar – wird mit Kickbase abgeglichen" if status == "unknown" else "fehlgeschlagen"
            message = f"{action.name}: {_verb(action)} {word} ({e})"
            self.automation.record(user_id, league.id, "trader", message, ok=False, details={"player_id": action.player_id, "status": status})
            if status == "unknown":
                await self._push(user_id, "Autotrader: Status unklar", message, f"trader-{league.id}")
            if isinstance(e, KickbaseAuthError):
                raise
            return status
        if action.kind == "sell":
            after = None
            try:
                after = (await client.own_budget(league.id)).budget
            except KickbaseError as e:
                log.info("Balance after a sale not read: %s", e)
            received = after - before if after is not None and before is not None else None
            await asyncio.to_thread(self._finish_sale, league, user_id, entry_id, action, received)
            message = f"{action.name} verkauft ({action.reason})" + (f" für {received / 1e6:.2f} Mio. €" if received else ", Erlös unbekannt")
        else:
            await asyncio.to_thread(self._finish_entry, entry_id, "open")
            message = f"Gebot {action.price / 1e6:.2f} Mio. € für {action.name} ({action.reason})"
        self.automation.record(user_id, league.id, "trader", message, details={"player_id": action.player_id, "purpose": action.purpose})
        await self._push(user_id, "Autotrader", message, f"trader-{league.id}")
        return "done"

    async def _still_open(self, league: League, client: KickbaseClient, player_id: str) -> bool:
        market = await client.market(league.id)
        listing = next((p for p in market.players if p.id == player_id), None)
        ### `expires_in`: seconds until the auction ends, as Kickbase sends it with the market
        return listing is not None and (listing.expires_in is None or listing.expires_in > 60)

    async def _withdraw(self, league: League, user_id: str, client: KickbaseClient, action: Action) -> str:
        """Only the trader's own bid, checked again right before. The bid's log entry is closed by
        `_settle` once the market shows no own bid anymore."""
        try:
            market = await client.market(league.id)
            listing = next((p for p in market.players if p.id == action.player_id), None)
            offer_id = listing.own_offer_id(user_id) if listing else None
            if listing is not None and listing.own_bid(user_id) != action.price:
                return "skipped" # A manually changed bid no longer belongs to this plan.
            if offer_id is None:
                ### An own bid without a usable offer id: withdrawing cannot work, the bid stays (and
                ### stays counted as spent)
                if listing is not None and listing.own_bid(user_id) is not None:
                    self.automation.record(user_id, league.id, "trader", f"{action.name}: Gebot hat keine Angebots-ID, nicht zurückgezogen", ok=False)
                    return "failed"
                return "skipped"
            await client.withdraw_offer(league.id, action.player_id, offer_id)
            ### Checked, not assumed
            after = await client.market(league.id)
            still = next((p for p in after.players if p.id == action.player_id), None)
            if still is not None and still.own_bid(user_id) is not None:
                self.automation.record(user_id, league.id, "trader", f"{action.name}: Kickbase hat das Gebot nicht zurückgezogen", ok=False)
                return "failed"
        except KickbaseAuthError:
            raise
        except KickbaseError as e:
            self.automation.record(user_id, league.id, "trader", f"{action.name}: Gebot zurückziehen fehlgeschlagen – {e}", ok=False, details={"api_error": True})
            return "failed"
        message = f"Gebot für {action.name} zurückgezogen ({action.reason})"
        self.automation.record(user_id, league.id, "trader", message, details={"player_id": action.player_id, "purpose": action.purpose})
        await self._push(user_id, "Autotrader", message, f"trader-{league.id}")
        return "done"

    ### ==============================================================================================
    ### Settling the own bids, and learning from them
    ### ==============================================================================================

    def _settle(self, league: League, user_id: str, squad: kb.ManagerSquad, market: kb.Market, now: datetime) -> None:
        listed = {p.id: p for p in market.players}
        owned = {p.id: p for p in squad.players}
        with Session(self.engine) as session:
            ### Calls whose outcome was not confirmed (timeout, server error, restart): Kickbase decides
            for entry in session.exec(
                select(TradeLog).where(TradeLog.user_id == user_id, TradeLog.league_id == league.id, TradeLog.status.in_(t.UNSETTLED))
            ).all():
                ### "failed" only on positive evidence: a bid whose listing is still there without it, a
                ### sale whose player is still in the squad. A listing that is gone may have been won or
                ### lost with this bid: it stays unclear (and blocks new buys) until the transfer is synced
                bid_there = entry.player_id in listed and listed[entry.player_id].own_bid(user_id) is not None
                if entry.kind == "bid" and (bid_there or entry.player_id in owned):
                    entry.status = "open" # Settled below like every open bid
                elif entry.kind == "bid" and entry.player_id not in listed:
                    if self._transfer_after(session, league.id, entry.player_id, entry.at) is not None:
                        entry.status = "open" # Won or lost: settled below from the transfer
                    elif now - entry.at > UNSETTLED_GIVE_UP:
                        entry.status, entry.resolved_at = "expired", now
                    else:
                        continue
                elif entry.kind == "sell" and entry.player_id not in owned:
                    entry.status, entry.resolved_at = "sold", now # Proceeds unknown: price is the estimate
                    entry.details = {**entry.details, "received_known": False}
                elif now - entry.at > RECONCILE_AFTER:
                    entry.status, entry.resolved_at = "failed", now
                else:
                    continue
                session.add(entry)
            session.flush()
            rows = session.exec(
                select(TradeLog).where(
                    TradeLog.user_id == user_id, TradeLog.league_id == league.id, TradeLog.kind == "bid", TradeLog.status == "open"
                )
            ).all()
            if not rows:
                session.commit()
                return
            with self._learning():
                base, local = self._load_states(session, league.id)
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
                        base, local = _auction(base, local, entry.market_value, True, entry.price, None)
                    else:
                        sale = self._transfer_after(session, league.id, entry.player_id, entry.at)
                        if sale is not None and sale.buyer_id != user_id:
                            entry.status = "lost"
                            entry.details = {**entry.details, "winner_id": sale.buyer_id, "winner_price": sale.price}
                            base, local = _auction(base, local, entry.market_value, False, entry.price, sale.price)
                        elif now - entry.at > timedelta(days=1):
                            entry.status = "expired" # Gone without a transfer the sync saw: nothing learned
                        else:
                            continue # The sync has not stored the transfer yet
                    entry.resolved_at = now
                    session.add(entry)
                self._save_states(session, league.id, base, local)
                session.commit()

    @staticmethod
    def _transfer_after(session: Session, league_id: str, player_id: str, since: datetime) -> Transfer | None:
        return session.exec(
            select(Transfer)
            .where(Transfer.league_id == league_id, Transfer.player_id == player_id, Transfer.date >= since - timedelta(hours=1))
            .order_by(Transfer.date)
        ).first()

    def _save_state(self, session: Session, state: t.Learned, key: str = STATE_KEY) -> None:
        row = session.get(ModelState, key) or ModelState(key=key)
        row.data = state.dump()
        row.updated_at = utcnow()
        session.add(row)

    @staticmethod
    def _load_states(session: Session, league_id: str) -> tuple[t.Learned, t.Learned]:
        """The global base model and the league's own one (bid heights and auction counts)."""
        return t.Learned.load(load_state(session, STATE_KEY)), t.Learned.load(load_state(session, f"{STATE_KEY}:{league_id}"))

    def _save_states(self, session: Session, league_id: str, base: t.Learned, local: t.Learned) -> None:
        self._save_state(session, base)
        self._save_state(session, local, f"{STATE_KEY}:{league_id}")

    def learned_for(self, league_id: str) -> t.Learned:
        """What one league trades with: global base, its own bid heights mixed in (`t.blend`)."""
        with Session(self.engine) as session:
            return t.blend(*self._load_states(session, league_id))

    ### ==============================================================================================
    ### Shadow trades
    ### ==============================================================================================

    def _start_shadows(self, league_id: str, shadows: list[ShadowTrade], user_id: str = "") -> None:
        """One open paper trade per player and kind in the league (whoever's trader started it), so the
        same auction is never learned twice. Only the user whose trader started it sees it."""
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
                    shadow.league_id, shadow.user_id = league_id, user_id
                    session.add(shadow)
                    open_keys.add((shadow.player_id, shadow.kind))
            session.commit()

    def _settle_shadows(self, league: League, market: kb.Market, now: datetime, learn: bool = True) -> None:
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
            with self._learning(): # Read, learn and write without another round in between
                base, local = self._load_states(session, league.id)
                ### Each paper trade with the sale ratio of the user whose trader started it (the default
                ### for paper trades without an owner)
                learned_ratio = learned_sell_ratio(session)
                settings = {
                    r.user_id: r.trader_options
                    for r in session.exec(select(UserAutomation).where(UserAutomation.league_id == league.id)).all()
                }
                ratios = {uid: t.sell_ratio(t.Options.load(settings.get(uid)), learned_ratio) for uid in {s.user_id for s in rows}}
                for s in rows:
                    ratio = ratios[s.user_id]
                    points = histories.get(s.player_id) or []
                    last_day = points[-1][0] if points else None
                    if s.kind == "sell":
                        due = analytics.market_value_day(s.at) + t.REGRET_DAYS
                        if last_day is None or last_day < due:
                            continue
                        s.value_after = analytics.value_on_day(points, due) or points[-1][1]
                        ### What holding would have brought more, net of the sale ratio
                        s.result = int((s.value_after - s.market_value) * ratio)
                        if s.purpose != "rescue": # Forced sales say nothing about the swap edge
                            base = t.after_regret(base, s.result)
                        s.status = "done"
                    elif s.status == "watching":
                        if s.player_id in listed:
                            continue
                        sale = self._transfer_after(session, league.id, s.player_id, s.at)
                        if sale is not None and sale.price != s.bid:
                            won = sale.price < s.bid
                            base, local = _auction(base, local, s.market_value, won, s.bid, sale.price, t.SHADOW_WEIGHT)
                            s.winner_price = sale.price
                            if won:
                                s.status, s.paid, s.won_day = "holding", s.bid, analytics.market_value_day(sale.date)
                            else:
                                s.status = "lost"
                        elif sale is not None:
                            ### A tie: who gets it is unknown, so it teaches nothing
                            s.status, s.winner_price = "lost", sale.price
                        elif now - s.at > timedelta(days=2):
                            ### Gone without a transfer (no buyer, withdrawn, relisted): not a won auction
                            s.status = "expired"
                        else:
                            continue
                    else: # holding
                        due = (s.won_day or 0) + t.PROFIT_HOLD
                        if last_day is None or last_day < due:
                            continue
                        s.value_after = analytics.value_on_day(points, due) or points[-1][1]
                        s.result = int(s.value_after * ratio) - (s.paid or s.bid)
                        base = t.after_forecast(base, s.forecast_gain, s.value_after - s.market_value, t.SHADOW_WEIGHT)
                        if s.purpose == "profit":
                            base = t.after_sale(base, s.result, t.SHADOW_WEIGHT)
                        s.status = "done"
                    s.resolved_at = now if s.status in ("done", "lost", "expired") else None
                    session.add(s)
                ### Shadow trades switched off: open ones are still closed for the statistics, nothing is learned
                if learn:
                    self._save_states(session, league.id, base, local)
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
        config: tuple[int, t.Options] | None = None,
    ) -> tuple[list[Action], list[ShadowTrade]]:
        from api.insights import Insights
        from api.routes import analysis_limits

        started = time.monotonic()
        ### The round's configuration (E02.04); planned on its own (tests, re-planning) the active one
        config_version, opts = config or self.configs.options(row.user_id, league.id)
        min_play = opts.min_play / 100
        user_id = row.user_id
        own_ids = [p.id for p in squad.players]
        listed = {p.id: p for p in market.players}
        expiries = {p.id: now + timedelta(seconds=p.expires_in) if p.expires_in is not None else None
                    for p in market.players}
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
            insight = Insights(session, league, user_id, self.automation.model, max_squad, max_club)
            offers = {
                o.id: o
                for o in insight.market()
                if o.id in listed
            }
            state = t.blend(*self._load_states(session, league.id))
            shares = insight.winning_shares()
            ### The league's setting; a learned ratio only ever lowers it
            ratio = t.sell_ratio(opts, learned_sell_ratio(session))
            history = self._trades(session, user_id, league.id)

        ### Only what really reached Kickbase counts: dry run entries ("planned") and failed calls
        ### never use up limits, never block a player and never make a profit or loss
        real = [h for h in history if h.status not in ("planned", "failed")]
        local = now.astimezone(analytics.MARKET_VALUE_TIMEZONE)
        midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
        today = [h for h in real if h.at >= midnight]
        bids_left = opts.daily_bids - sum(1 for h in today if h.kind == "bid")
        sales_left = opts.daily_sales - sum(1 for h in today if h.kind == "sell" and h.purpose != "rescue")
        sold_recently = {h.player_id for h in real if h.kind == "sell" and now - h.at < t.REBUY_BLOCK}
        unsettled = {h.player_id for h in real if h.status in t.UNSETTLED}
        bought = {h.player_id: h for h in real if h.kind == "bid" and h.status == "won"}
        week = t.week_of(now)
        ### Weekly stop-loss of the profit trading: realized losses of profit positions this week, plus
        ### what the open profit positions would lose if sold now (computed below with the squad).
        ### Sporting transfers and rescue sales do not count. 0 switches it off; exactly the limit pauses.
        week_profit = sum(
            h.profit or 0 for h in real
            if h.kind == "sell" and h.purpose in EXIT_PURPOSES and t.week_of(h.resolved_at or h.at) == week
        )
        scale = state.gain_scale
        raw_gain: dict[str, int] = {}
        predicted: dict[str, tuple[int, int, int]] = {} # Value, forecast after 1 and 2 updates, unscaled

        def candidate(pid: str, position: int, status: int, team_id: str | None, average: int | None, value: int) -> t.Candidate:
            e = context.expectation(pid, position, status, team_id, average)
            points = histories.get(pid) or []
            prediction = coach.forecast(points, self.automation.model, t.PROFIT_HOLD, context.match_points(pid))
            raw_gain[pid] = prediction.projection[-1] if prediction else 0
            if prediction:
                predicted[pid] = (value, prediction.next_change, raw_gain[pid])
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
                ahead=context.expectation_ahead(pid, position, status, team_id, average),
                samples=context.samples(pid),
            )

        ### Starters: kept around the kick-off; without the automatic lineup also between matchdays,
        ### because nobody would fill the gap
        live = coach.live_matchday(context.fixtures, now) is not None
        keep_starters = t.starters_locked(context.fixtures, now, opts.starter_lock) or (not live and not row.auto_lineup)
        own = []
        for p in squad.players:
            own.append(candidate(p.id, p.position, p.status, p.team_id, p.average_points, p.market_value))
        own = _with_best(own)
        ### Starters are the lineup saved at Kickbase. When it cannot be read, nobody is assumed to sit
        ### on the bench: while starters are kept, every fit player is
        starters = set(saved) if saved else {c.player_id for c in own}
        locked_own = []
        for c in own:
            held = bought.get(c.player_id)
            fresh = held is not None and c.fit and now - (held.resolved_at or held.at) < t.MIN_HOLD
            locked_own.append(replace(c, locked=fresh or (keep_starters and c.player_id in starters)))
        own = locked_own
        names = {p.id: p.last_name for p in squad.players} | {p.id: p.last_name for p in market.players}
        cost_of = {p.id: p.purchase_price for p in squad.players} # Kept before a sale removes the entry
        actions: list[Action] = []
        upcoming = context.upcoming
        deadline = upcoming.deadline if upcoming is not None else None
        repay_from = t.repay_from(deadline) if deadline is not None else None
        stage = t.phase(now, deadline)
        ### The bench this round keeps (E05.02). The league's strategy counts only with the flag
        ### flexible_bench, and only where nothing it changes reaches Kickbase or the flag is live;
        ### otherwise the full bench of 2.0, and the alternative is only logged (shadow)
        stored_flags = flags.load(row.trader_flags)

        def applies(name: str) -> bool:
            stage_now = flags.effective(stored_flags, name, row.trader_live)
            return stage_now == flags.LIVE or (stage_now == flags.DRY_RUN and not row.trader_live)

        def watched(name: str) -> bool:
            return stored_flags[name] != flags.OFF

        bench_flag = flags.effective(stored_flags, "flexible_bench", row.trader_live)
        bench_wanted = t.bench_mode(opts.bench_strategy, stage)
        bench = bench_wanted if applies("flexible_bench") else t.BENCH_FULL
        team_value = sum(p.market_value or 0 for p in squad.players)

        ### Open profit positions: bought by the trader for profit, still owned. Their purchase price is
        ### the won bid's, else the one Kickbase shows; unknown stays out of every sum
        positions = {
            c.player_id: (c, cost)
            for c in own
            if (h := bought.get(c.player_id)) is not None and h.purpose == "profit"
            and (cost := h.paid or cost_of.get(c.player_id)) is not None
        }
        unrealized = sum(int(c.value * ratio) - cost for c, cost in positions.values())
        paused = opts.stop_loss > 0 and (week_profit <= -opts.stop_loss or week_profit + min(unrealized, 0) <= -opts.stop_loss)

        ### Open bids: every one counts as spent, and as a player to come (projected squad). Never as
        ### a player who is there (confirmed squad): sales, cover and credit only look at `own`
        open_bids = {pid: bid for pid, p in listed.items() if (bid := p.own_bid(user_id)) is not None}
        trader_bids = {h.player_id: h for h in real if h.kind == "bid" and h.status == "open" and h.player_id in open_bids}
        pending = {
            pid: replace(
                candidate(pid, p.position, p.status, p.team_id, p.average_points, p.market_value), locked=True,
                expires_at=expiries[pid],
            )
            for pid, p in listed.items() if pid in open_bids
        }

        ### Sales already counted for open trader bids of earlier rounds: never counted twice (E04.06)
        claimed_before = {
            c["player_id"] for h in trader_bids.values() for c in (h.details or {}).get("collateral") or [] if c.get("player_id")
        }
        ### Every planned action passes the risk engine against the confirmed state before it may run
        all_open, own0, bids0, sales0 = dict(open_bids), own, bids_left, sales_left
        loan = 0
        ### Per market player what only the planning knows, for the decision snapshots (E03.01)
        snapshot_extra: dict[str, dict] = {}

        def finish(planned_actions: list[Action], shadows: list[ShadowTrade], debug: dict, listings: dict[str, t.Candidate]):
            ctx = risk.Context(
                now=now, switches_on=self.settings.automation.trader and row.trader, deadline=deadline, budget=budget,
                reserve=opts.reserve, credit=loan, credit_mode=opts.credit_mode, open_bids=all_open,
                trader_bids=set(trader_bids), squad=own0, listings=listings,
                club_of={**{c.player_id: c.team_id for c in own0}, **{c.player_id: c.team_id for c in pending.values()},
                         **{pid: c.team_id for pid, c in listings.items()}},
                max_squad=max_squad, max_club=max_club, bids_left=bids0, sales_left=sales0, blocked=unsettled | sold_recently,
                ratio=ratio, min_margin=state.min_margin, min_roi=opts.min_roi / 100, rescue_override=opts.rescue_override,
                unconfirmed=bool(unsettled), bench=bench,
                collateral={a.player_id: list(a.collateral) for a in planned_actions if a.kind == "bid" and a.collateral},
                used_collateral=claimed_before, repay_from=repay_from,
            )
            codes = risk.validate(planned_actions, ctx)
            approved = [replace(a, config_version=config_version) for a, code in zip(planned_actions, codes, strict=True) if code is None]
            debug["config_version"] = config_version
            debug["risk_blocked"] = [
                {"kind": a.kind, "purpose": a.purpose, "player_id": a.player_id, "name": a.name, "price": a.price, "code": code}
                for a, code in zip(planned_actions, codes, strict=True) if code is not None
            ]
            debug["actions"] = [a.__dict__ for a in approved]
            for m in debug.get("market", []):
                code = next((b["code"] for b in debug["risk_blocked"] if b["player_id"] == m["id"]), None)
                if code:
                    m["decision"] += f" – blockiert: {code}"
                    m["reason"], m["reasons"] = rc.RISK_BLOCKED, [code, *(r for r in m.get("reasons", []) if r != code)]
            ### The eleven: what is there for sure, and with every open and new bid won
            new = [listings[a.player_id] for a in approved if a.kind == "bid" and a.player_id in listings]
            debug["gaps_confirmed"] = t.best_of(own0).empty_slots if own0 else 11
            debug["gaps_projected"] = t.best_of([*own0, *pending.values(), *new]).empty_slots if own0 or pending or new else 11
            debug["runtime_ms"] = int((time.monotonic() - started) * 1000)
            if "market" in debug:
                self._snapshot(league.id, row, debug, listed, snapshot_extra, now, opts)
            self._notify(league.id, user_id, debug, stage, deadline, now)
            self._log_debug(league.id, user_id, debug)
            return approved, [s for s in shadows if s.player_id not in {a.player_id for a in approved}]

        ### A negative balance at the deadline costs the whole matchday. From the last market value update
        ### before it on (sales fetch the same then as an hour before kick-off, and a server that is down
        ### for a while still has many rounds left): first the trader's bids that could still make it
        ### negative are withdrawn, then a negative balance is sold back to zero. One sale per round, the
        ### next round re-plans with the confirmed balance
        if stage in ("repay", "final"):
            due = {pid: bid for pid, bid in open_bids.items() if pending[pid].expires_at is None or pending[pid].expires_at <= deadline}
            worst = budget - sum(due.values())
            for pid in sorted((p for p in due if p in trader_bids), key=lambda p: _purpose_rank(trader_bids[p].purpose)):
                if worst >= 0:
                    break
                actions.append(Action("withdraw", trader_bids[pid].purpose, pid, names.get(pid, pid), open_bids.pop(pid), pending[pid].value, reason="Kontostand zum Spieltag sichern"))
                worst += due[pid]
            if budget < 0:
                plan = coach.rescue_sales(
                    budget,
                    [coach.SellCandidate(c.player_id, c.position, c.expected, int(c.value * ratio)) for c in own],
                    protected=[] if opts.rescue_override else [c.player_id for c in own if c.locked and c.fit],
                )
                by_id = {c.player_id: c for c in own}
                actions += [
                    Action("sell", "rescue", pid, names.get(pid, pid), int(by_id[pid].value * ratio), by_id[pid].value,
                           reason="Budget im Minus vor der Deadline", cost=cost_of.get(pid))
                    for pid in plan.sales
                ]
            if budget < 0 or worst < 0:
                after = budget + sum(a.price for a in actions if a.kind == "sell")
                if after < 0 or worst < 0:
                    self._warn_debt(league, user_id, min(after, worst), deadline)
                return finish(actions, [], {
                    "live": row.trader_live, "phase": stage, "budget": budget, "worst_case": worst, "rescue": True,
                    "deadline": deadline.isoformat(), "repay_from": repay_from.isoformat(),
                }, {})

        ### Profit positions: hold or sell, every round (the price is the same all day until 22:00).
        ### One exit per round, the most urgent reason first; never a locked player, never one of the
        ### best eleven, never the last cover. Every position's verdict goes to the debug log
        exits: dict[str, str] = {}
        urgent: list[tuple[int, t.Candidate, str, str]] = []
        for pid, (c, cost) in positions.items():
            held = bought[pid]
            since = analytics.market_value_day(held.resolved_at or held.at)
            peak = max((int(v) for d, v in (histories.get(pid) or []) if d >= since), default=None)
            verdict = t.exit_reason(c, cost, peak, (now - (held.resolved_at or held.at)).days, ratio, state.min_margin, opts)
            if verdict is None:
                exits[pid] = "halten"
            elif c.locked or c.in_best or not t.keeps_cover(own, c, bench):
                exits[pid] = f"{verdict[0]}, aber geschützt (gesperrt, Startelf oder letzter Ersatz)"
            else:
                exits[pid] = verdict[0]
                urgent.append((EXIT_ORDER.index(verdict[0]), c, verdict[0], verdict[1]))
        if urgent and sales_left > 0:
            _, c, code, text = min(urgent, key=lambda u: u[0])
            actions.append(
                Action("sell", "exit", c.player_id, names.get(c.player_id, c.player_id), int(c.value * ratio), c.value,
                       reason=f"{text} ({code})", cost=positions[c.player_id][1])
            )
            own = _with_best([o for o in own if o.player_id != c.player_id])
            sales_left -= 1

        ### The trader's own bids that are not needed anymore (a rival won the slot's other auction, a
        ### player was won) are withdrawn, the most useful kept first; the user's own bids never
        planned = [*own, *(c for pid, c in pending.items() if pid not in trader_bids)]
        for c in sorted((pending[pid] for pid in trader_bids if pid in open_bids), key=lambda c: (_purpose_rank(trader_bids[c.player_id].purpose) * -1, -c.expected)):
            purpose = trader_bids[c.player_id].purpose
            needed = (
                t.lineup_upgrade(planned, c, opts) is not None if purpose == "lineup"
                else c.position in t.missing_cover(planned, bench) if purpose == "cover"
                else True
            )
            if needed:
                planned.append(c)
                continue
            actions.append(Action("withdraw", purpose, c.player_id, names.get(c.player_id, c.player_id), open_bids.pop(c.player_id), c.value, reason="kein Bedarf mehr"))
        planned = _with_best(planned)

        ### Money: the balance minus reserve and every open bid. Planned sales bring nothing until
        ### Kickbase confirmed them (a bid that needs them waits for the next round)
        free = budget - opts.reserve - sum(open_bids.values())
        slots = max_squad - len(own) - len(open_bids)
        ### Credit only as far as selling sellable players (simulated one by one) pays it back
        liquidation = t.liquidation_value(own, ratio, max(sales_left, 0), bench)
        scenario_liquidation = {
            name: finance.liquidation(own, ratio, max(sales_left, 0), bench, name, 0, scale) for name in finance.SCENARIOS
        }
        if applies("scenario_credit"):
            liquidation = scenario_liquidation["pessimistic"]
        loan = t.credit(budget, team_value, liquidation)
        ### Profit trades together never tie up more than `profit_share` of team value plus balance
        holdings = sum(c.value for c in own if (h := bought.get(c.player_id)) is not None and h.purpose == "profit")
        profit_room = int((team_value + budget) * opts.profit_share / 100) - holdings - sum(
            bid for pid, bid in open_bids.items() if pid in trader_bids and trader_bids[pid].purpose == "profit"
        )

        ### The max bid next to the money released per purpose (for an auction ending before the deadline),
        ### with every limit that makes up the difference. Diagnosis only, the bids below decide on their own
        money_check = t.money_check(
            budget, team_value, sum(open_bids.values()), opts.reserve, loan,
            {p: risk.credit_for(p, None, stage, deadline, loan, opts.credit_mode) for p in ("lineup", "cover", "profit")},
            {p: risk.credit_for(p, None, "normal", None, loan, opts.credit_mode) for p in ("lineup", "cover", "profit")},
            profit_room,
        )

        def money_for(c: t.Candidate, cash: int, purpose: str) -> int:
            return cash + risk.credit_for(purpose, c.expires_at, stage, deadline, loan, opts.credit_mode)

        ### Conditional financing (E04.04 profit target, E04.05 the starter pushed out): a sale that only
        ### becomes possible once the bid is won. Each player backs one bid at most; "final" plans none
        claimed = set(claimed_before)
        conditional_log: dict[str, dict] = {}

        def collateral_for(c: t.Candidate, purpose: str, upgrade: t.Upgrade | None) -> finance.Collateral | None:
            if stage == "final":
                return None
            if purpose == "profit" and watched("conditional_repayment"):
                found, flag = finance.self_collateral(c, ratio, now, repay_from), "conditional_repayment"
            elif purpose == "lineup" and upgrade is not None and not upgrade.fills and watched("upgrade_financing"):
                found, flag = finance.replaced_collateral(own, c, upgrade.replaced, ratio, bench, now, repay_from), "upgrade_financing"
            else:
                return None
            if found is None or found.player_id in claimed:
                return None
            used = applies(flag)
            conditional_log[c.player_id] = {"kind": found.kind, "player_id": found.player_id, "value": found.value,
                                            "sell_until": found.sell_until.isoformat(), "applied": used}
            return found if used else None

        market_candidates: list[t.Candidate] = []
        for pid, p in listed.items():
            offer = offers.get(pid)
            seller = p.seller.id if p.seller else None
            if offer is None or seller == user_id or pid in pending or pid in sold_recently or pid in unsettled or offer.own_club_full:
                continue
            if expiries[pid] is not None and expiries[pid] <= now:
                continue
            c = candidate(pid, p.position, p.status, p.team_id, p.average_points, p.market_value)
            market_candidates.append(
                replace(c, price=p.price or p.market_value, bid_low=offer.bid_low or 0, bid_high=offer.bid_high or 0, expires_at=expiries[pid])
            )
        free_agents = {pid for pid, p in listed.items() if p.seller is None}

        ### Why each market player was or was not bought, for the debug log: a text, and reason codes
        ### (core.reasons, primary first) that a log, export or the UI can count
        why: dict[str, str] = {}
        codes: dict[str, list[str]] = {}
        upgrade_codes: dict[str, str] = {}

        def mark(pid: str, text: str, *found: str) -> None:
            why[pid] = text
            codes[pid] = [code for code in found if code]

        def add(pid: str, text: str, code: str) -> None:
            why[pid] += text
            codes.setdefault(pid, []).append(code)

        for pid, p in listed.items():
            if pid in pending:
                mark(pid, "eigenes Gebot offen", rc.OWN_BID_OPEN)
            elif p.seller is not None and p.seller.id == user_id:
                mark(pid, "eigener Spieler", rc.OWN_PLAYER)
            elif pid in sold_recently:
                mark(pid, "vor kurzem verkauft", rc.REBUY_BLOCK)
            elif pid in unsettled:
                mark(pid, rc.TEXT[rc.UNCONFIRMED_ACTION], rc.UNCONFIRMED_ACTION)
            elif pid in offers and offers[pid].own_club_full:
                mark(pid, "Vereinslimit", rc.CLUB_LIMIT)
            elif pid not in offers:
                mark(pid, "keine Marktdaten", rc.NO_MARKET_DATA)
            elif expiries[pid] is not None and expiries[pid] <= now:
                mark(pid, rc.TEXT[rc.AUCTION_EXPIRED], rc.AUCTION_EXPIRED)

        options: list[tuple[tuple[int, float], str, t.Candidate, t.Upgrade | None]] = []
        ### Order by phase (t.priority): normally fill the eleven, improve it, profit, substitutes;
        ### close to the matchday fill, substitutes, improve, profit last
        for c in market_candidates:
            upgrade, upgrade_code = t.upgrade_check(planned, c, opts)
            if upgrade_code:
                upgrade_codes[c.player_id] = upgrade_code
            if upgrade is not None:
                options.append((t.priority("lineup", upgrade.fills, stage, upgrade.gain), "lineup", c, upgrade))
            elif row.trader_profit and not paused and not state.forecast_pause and c.fit and c.forecast > 0 and c.expires_at is not None and stage != "final":
                ### Ranked by net return per euro and update at the lowest bid, not by the absolute gain
                low = t.bid_for(c, 0.0, None)
                options.append((t.priority("profit", False, stage, t.profit_rank(c, low, ratio) if low else -1.0), "profit", c, None))
            else:
                code = (
                    rc.NOT_FIT if not c.fit
                    else rc.PROFIT_TRADING_OFF if not row.trader_profit
                    else rc.STOP_LOSS if paused
                    else rc.FORECAST_PAUSE if state.forecast_pause
                    else rc.PHASE_FINAL if stage == "final"
                    else rc.AUCTION_END_UNKNOWN if c.expires_at is None and c.forecast > 0
                    else rc.NO_RISING_FORECAST
                )
                mark(c.player_id, rc.TEXT[code] if code == rc.NOT_FIT else f"kein Startelf-Upgrade, {rc.TEXT[code]}",
                     code, upgrade_codes.get(c.player_id) if code != rc.NOT_FIT else None)
        cover_pool = [c for c in market_candidates if not any(o[2] is c for o in options if o[1] == "lineup")]
        for c in cover_pool:
            if c is t.cover_target(planned, [c], opts, bench):
                options.append((t.priority("cover", False, stage, -max(c.bid_low, c.price, c.value)), "cover", c, None))
        options.sort(key=lambda o: o[0], reverse=True)
        ### Paper trades: the best profit candidate of each price class first, then the next best, so
        ### the learning does not only see the most promising (expensive) players
        ranked_profit = [o[2] for o in options if o[1] == "profit"]
        by_class: dict[int, list[t.Candidate]] = {}
        for c in ranked_profit:
            by_class.setdefault(coach.price_class(c.value), []).append(c)
        spread = [c for rank in range(len(ranked_profit)) for group in by_class.values() if rank < len(group) for c in [group[rank]]]
        shadow_ids = {c.player_id for c in spread[:SHADOWS_PER_ROUND]}
        money_seen: dict[str, int] = {}
        snapshot_caps = {}
        snapshots_on = watched("decision_snapshots")

        shadows: list[ShadowTrade] = []
        sold_now = any(a.kind == "sell" for a in actions)
        bid_on: set[str] = set()
        for _, purpose, c, upgrade in options:
            if c.player_id in bid_on:
                continue
            profit = purpose == "profit"
            extra = state.extra[coach.price_class(c.value)]
            if profit and c.player_id in shadow_ids:
                ### On paper at the realistic bid. "near": the rules would have passed on it. Only
                ### "profit" ones move the minimum margin, the rejected ones would bias it upwards
                paper = t.bid_for(c, extra, None)
                if paper is not None:
                    rule_bid = t.bid_for(c, extra, t.max_profit_bid(c, ratio, state.min_margin, opts.min_roi / 100))
                    qualified = rule_bid is not None and t.is_profit_buy(c, rule_bid, state.min_margin, ratio, opts.min_roi / 100)
                    shadows.append(
                        _shadow_buy(c, rule_bid if qualified else paper, raw_gain.get(c.player_id, 0),
                                    "profit" if qualified else "near", c.player_id in free_agents)
                    )
            label = {"lineup": "Startelf", "profit": "Gewinnhandel", "cover": "Ersatz"}[purpose]
            if bids_left <= 0:
                mark(c.player_id, f"{label}: Tageslimit Gebote erreicht", rc.DAILY_BIDS)
                continue
            ### Needs change with every bid of this round
            gaps = t.best_of(planned).empty_slots
            if purpose == "lineup":
                upgrade, upgrade_code = t.upgrade_check(planned, c, opts)
                if upgrade is None:
                    mark(c.player_id, "Startelf: Platz schon durch ein Gebot dieser Runde besetzt", rc.SLOT_TAKEN, upgrade_code)
                    continue
            elif gaps > 0 or (purpose == "cover" and c.position not in t.missing_cover(planned, bench)):
                if gaps > 0:
                    mark(c.player_id, f"{label}: erst die Startelf füllen", rc.ELEVEN_GAPS_FIRST)
                else:
                    mark(c.player_id, "Ersatz: Position schon abgedeckt", rc.COVER_DONE)
                continue # The eleven comes first, profit and substitutes wait for it
            ### Keep enough to fill the other empty slots cheaply, and a profit trade leaves the money for
            ### every missing substitute, so profit never crowds out the bench for good
            keep = max(t.best_of([*planned, c]).empty_slots, 0) * opts.cover_max_price
            if purpose == "profit":
                keep += len(t.missing_cover(planned, bench)) * opts.cover_max_price
            backing = collateral_for(c, purpose, upgrade)
            money_seen[c.player_id] = money_for(c, free, purpose) - keep + (backing.value if backing else 0)
            if snapshots_on:
                # Only confirmed opening funds and unconditional credit; never include a planned sale.
                cash = min(free, budget - opts.reserve - sum(open_bids.values()))
                available = money_for(c, cash, purpose) - keep
                cap = min(available, profit_room) if profit else int(available * opts.lineup_share / 100)
                snapshot_caps.setdefault(c.player_id, min(cap, money_check["max_bid_free"]))
            bid = _price(c, purpose, upgrade, extra, money_seen[c.player_id], opts, state, ratio, profit_room, shares) if slots > 0 else None
            sale = None
            if bid is None:
                ### Each limit on its own: what does not pay first, then what money or room is missing
                found = [rc.SQUAD_FULL] if slots <= 0 else rc.price_blockers(
                    c, purpose, upgrade, money_seen[c.player_id], opts, state.min_margin, ratio, profit_room
                )
                ### Why the money is short: the limits of the max bid check, largest first
                limits = rc.money_limits(money_check, purpose) if rc.BUDGET in found else []
                mark(c.player_id, f"{label}: " + " und ".join(rc.TEXT[code] for code in found), *found, *limits)
                ### Room or money is only made right before the auction ends, one sale per round
                if purpose == "cover" or sold_now or sales_left <= 0 or c.expires_at is None:
                    continue
                if c.expires_at - now > timedelta(minutes=opts.sell_window):
                    add(c.player_id, ", Verkauf erst im Verkaufsfenster", rc.ROOM_SALE_WINDOW)
                    continue
                ### Only the confirmed squad: the target may still be lost, the team has to be fine without him
                sale = t.pick_sale(own, c, min_play, state.swap_edge, bench)
                if sale is None:
                    add(c.player_id, ", kein Spieler, der auch ohne den Neuzugang verzichtbar ist", rc.ROOM_SALE_NONE)
                    continue
                proceeds = int(sale.value * ratio)
                ### A player is given up for this one: bid high enough to have a good chance
                bid = _price(c, purpose, upgrade, max(extra, t.ROOM_EXTRA), money_for(c, free + proceeds, purpose) - keep + (backing.value if backing else 0),
                             opts, state, ratio, profit_room, shares, use_ev=False)
                if bid is None:
                    add(c.player_id, ", auch mit Verkauf nicht", rc.ROOM_SALE_NOT_ENOUGH)
                    continue
                reason = (
                    "verletzt/fällt aus" if not sale.fit
                    else "kein Stammspieler" if not sale.regular(min_play)
                    else f"Platz für {names.get(c.player_id)}"
                )
                actions.append(Action("sell", "room", sale.player_id, names.get(sale.player_id, sale.player_id), proceeds, sale.value,
                                      reason=reason, cost=cost_of.get(sale.player_id), for_player=c.player_id))
                own = [o for o in own if o.player_id != sale.player_id]
                planned = _with_best([o for o in planned if o.player_id != sale.player_id])
                free += proceeds
                slots += 1
                sales_left -= 1
                sold_now = True
            if upgrade is not None:
                reason = (
                    f"+{upgrade.gain:.0f} erw. Punkte in der Elf, {t.cost_per_point(upgrade, bid, ratio) / 1e3:.0f} Tsd. € je Punkt"
                    + (" (Lücke)" if upgrade.fills else f", bindet {bid / 1e6:.1f} Mio.")
                )
            elif purpose == "cover":
                reason = f"Ersatz für Position {c.position}"
            else:
                reason = f"Prognose {c.gain / 1e3:+.0f} Tsd. in {t.PROFIT_HOLD} Tagen"
            if backing is not None:
                reason += f", finanziert über den späteren Verkauf von {names.get(backing.player_id, backing.player_id)} (≥ {backing.value / 1e6:.1f} Mio.)"
                claimed.add(backing.player_id)
            actions.append(
                Action("bid", purpose, c.player_id, names.get(c.player_id, c.player_id), bid, c.value,
                       upgrade.gain if upgrade else 0, reason, raw_gain.get(c.player_id, 0),
                       collateral=(backing,) if backing is not None else ())
            )
            mark(c.player_id, f"{label}: Gebot {bid:,} € ({reason})", rc.BID_PLANNED)
            bid_on.add(c.player_id)
            planned = _with_best([*planned, replace(c, locked=True)])
            free -= bid
            slots -= 1
            bids_left -= 1
            if purpose == "profit":
                profit_room -= bid

        def player(c: t.Candidate) -> dict:
            return {
                "id": c.player_id, "name": names.get(c.player_id), "pos": c.position, "expected": round(c.expected, 1),
                "average": c.average, "form": c.form, "play": c.play, "fit": c.fit, "today": c.today, "forecast": c.forecast,
                "gain": c.gain, "value": c.value, "price": c.price, "bid_low": c.bid_low, "bid_high": c.bid_high,
                "expires_at": c.expires_at.isoformat() if c.expires_at else None, "in_best": c.in_best, "locked": c.locked,
                "net_at_low": t.expected_profit(c, low, ratio) if (low := t.bid_for(c, 0.0, None)) else None,
                "ahead": c.ahead, "samples": c.samples, "quality": t.quality(c),
                "p_win_at_low": t.win_probability(low, c.value, t.winning_markups(shares, c.value)) if low else None,
            }

        self._observe_forecasts(league.id, predicted, now)
        considered: dict[str, str] = {}
        for _, purpose, c, _ in options:
            considered.setdefault(c.player_id, purpose)
        for c in market_candidates:
            ev = None
            if snapshots_on:
                worth = t.expected_proceeds(c, ratio)
                ev = t.best_bid(replace(c, price=max(c.price, c.bid_low)), worth, worth, t.winning_markups(shares, c.value))
            snapshot_extra[c.player_id] = {
                "ev": ev[0] if ev else None, "cap": snapshot_caps.get(c.player_id),
                "forecast_2": raw_gain.get(c.player_id), "purpose": considered.get(c.player_id),
                "hypothetical_bid": t.bid_for(c, state.extra[coach.price_class(c.value)], None),
            }
        return finish(actions, shadows, {
            "live": row.trader_live, "profit_trading": row.trader_profit, "phase": stage, "budget": budget,
            "worst_case": budget - sum(all_open.values()), "cash_free": free, "credit": loan, "credit_mode": opts.credit_mode,
            ### The liquidation that limited the credit (sales left today, after this round's exit sale), and
            ### for comparison the one of the whole daily limit before it
            "liquidation": liquidation, "liquidation_full_day": t.liquidation_value(own0, ratio, opts.daily_sales, bench),
            "finance": {
                "scenarios": scenario_liquidation, "credit_from": "pessimistic" if applies("scenario_credit") else "current",
                "conditional": conditional_log, "claimed_before": sorted(claimed_before),
            },
            "bench": {
                "strategy": opts.bench_strategy, "flag": bench_flag, "wanted": bench_wanted, "applied": bench,
                "missing_cover": t.missing_cover(own0, bench),
                ### What the league's strategy would free, also while only the full bench applies
                "liquidation_wanted": t.liquidation_value(own0, ratio, max(sales0, 0), bench_wanted),
                "missing_cover_wanted": t.missing_cover(own0, bench_wanted),
            },
            "profit_room": profit_room, "money_check": money_check,
            "reserve": opts.reserve, "open_bids": all_open, "slots": slots, "bids_left": bids_left, "sales_left": sales_left,
            "paused": paused, "week_profit": week_profit, "unrealized": unrealized,
            "forecast_paused": bool(state.forecast_pause), "league_auctions": len(shares),
            "learned": {"extra": list(state.extra), "min_margin": state.min_margin, "gain_scale": state.gain_scale, "swap_edge": state.swap_edge},
            "priorities": "nah am Spieltag: Lücke > Ersatz > Verbesserung > Gewinn" if stage != "normal" else "normal: Lücke > Verbesserung > Gewinn > Ersatz",
            "positions": {pid: {"cost": cost, "net_now": int(c.value * ratio) - cost, "verdict": exits.get(pid)} for pid, (c, cost) in positions.items()},
            "keep_starters": keep_starters, "lineup_known": bool(saved), "sell_ratio": ratio,
            "flags": flags.all_effective(flags.load(row.trader_flags), row.trader_live),
            "deadline": deadline.isoformat() if deadline else None,
            "repay_from": repay_from.isoformat() if repay_from else None,
            "squad": [player(c) for c in own0], "pending": [player(c) for c in pending.values()],
            "market": [
                {**player(c), "money": money_seen.get(c.player_id), "decision": why.get(c.player_id, "nicht geprüft"),
                 **_reason_fields(codes.get(c.player_id), upgrade_codes.get(c.player_id))}
                for c in market_candidates
            ],
            "skipped": {pid: why[pid] for pid in listed if pid in why and pid not in {c.player_id for c in market_candidates}},
            "skipped_reasons": {pid: codes.get(pid, [rc.NOT_CHECKED]) for pid in listed
                                if pid in why and pid not in {c.player_id for c in market_candidates}},
        }, {c.player_id: c for c in market_candidates})

    ### ==============================================================================================
    ### Log
    ### ==============================================================================================

    ### Not decisions about buying: no snapshot
    SNAPSHOT_SKIP = (rc.OWN_PLAYER, rc.OWN_BID_OPEN, rc.NO_MARKET_DATA)

    def _snapshot(self, league_id: str, row: UserAutomation, debug: dict, listed: dict, extra: dict[str, dict],
                  now: datetime, opts: t.Options) -> None:
        """E03.01/E03.02: every market decision of the round, once per user and auction, from what the
        round already holds (no Kickbase call). Later rounds only note a changed reason. Only while the
        flag decision_snapshots is not off; a failure never stops a trading round."""
        if flags.effective(flags.load(row.trader_flags), "decision_snapshots", row.trader_live) == flags.OFF:
            return
        day = analytics.market_value_day(now)

        def auction_key(pid: str) -> str:
            listing = listed.get(pid)
            if listing is not None and listing.listed_at is not None:
                return listing.listed_at.isoformat()
            expires = next((m.get("expires_at") for m in debug["market"] if m["id"] == pid), None)
            return f"end:{expires[:13]}" if expires else f"day:{day}"

        common = {
            "phase": debug.get("phase") or "", "budget": debug.get("budget"), "open_bids": sum((debug.get("open_bids") or {}).values()),
            "released": (debug.get("money_check") or {}).get("released") or {}, "squad_size": len(debug.get("squad") or []),
            "gaps": debug.get("gaps_projected"), "config_version": debug.get("config_version"), "model_version": t.MODEL_VERSION,
            "sell_ratio": debug.get("sell_ratio"), "hold_updates": t.PROFIT_HOLD,
        }
        rows: dict[tuple[str, str], dict] = {}
        for m in debug["market"]:
            more = extra.get(m["id"], {})
            listing = listed.get(m["id"])
            rows[(m["id"], auction_key(m["id"]))] = {
                **common, "listed_at": listing.listed_at if listing is not None else None,
                "expires_at": datetime.fromisoformat(m["expires_at"]) if m.get("expires_at") else None,
                "value": m["value"], "price": m.get("price"), "bid_low": m.get("bid_low"), "bid_high": m.get("bid_high"),
                "forecast_1": m.get("forecast"), "forecast_2": more.get("forecast_2"), "gain": m.get("gain"),
                "expected": m.get("expected"), "play": m.get("play"), "samples": m.get("samples"), "fit": bool(m.get("fit")),
                "purpose": more.get("purpose"), "hypothetical_bid": more.get("hypothetical_bid"),
                "min_bid": max(m.get("bid_low") or 0, m.get("price") or 0, m["value"]) or None,
                "p_win_at_min": m.get("p_win_at_low"), "net_at_min": m.get("net_at_low"),
                "reason": m.get("reason") or rc.NOT_CHECKED, "reasons": m.get("reasons") or [],
            }
        for pid, found in (debug.get("skipped_reasons") or {}).items():
            listing = listed.get(pid)
            if not found or found[0] in self.SNAPSHOT_SKIP or listing is None:
                continue
            rows[(pid, auction_key(pid))] = {
                **common, "listed_at": listing.listed_at, "value": listing.market_value, "price": listing.price,
                "expires_at": now + timedelta(seconds=listing.expires_in) if listing.expires_in is not None else None,
                "reason": found[0], "reasons": found[1:],
            }
        try:
            with Session(self.engine) as session:
                shadow_analysis.record_closed_listings(session, row.user_id, league_id, listed)
                shadow_analysis.settle_due(session, row.user_id, league_id, now)
                stored = {
                    (r.player_id, r.auction): r for r in session.exec(select(DecisionSnapshot).where(
                        DecisionSnapshot.user_id == row.user_id, DecisionSnapshot.league_id == league_id,
                        tuple_(DecisionSnapshot.player_id, DecisionSnapshot.auction).in_(list(rows)))).all()
                }
                candidates = [si.Candidate(pid, auction, coach.price_class(v["value"]), v["reason"])
                              for (pid, auction), v in rows.items() if (pid, auction) not in stored]
                selected = set()
                if candidates:
                    snap = DecisionSnapshot
                    bucket = case(*[(snap.value < high, i) for i, (_, high) in enumerate(coach.PRICE_CLASSES[:-1])],
                                  else_=len(coach.PRICE_CLASSES) - 1)
                    counts = {(b, reason): n for b, reason, n in session.exec(
                        select(bucket, snap.reason, func.count()).where(snap.user_id == row.user_id,
                            snap.league_id == league_id).group_by(bucket, snap.reason))}
                    selected = {c.key for c in si.select_candidates(candidates, set(), counts,
                                opts.snapshot_limit)}
                for (pid, auction), values in rows.items():
                    if (pid, auction) not in stored and (pid, auction) not in selected:
                        continue
                    old = stored.get((pid, auction))
                    if old is None:
                        session.add(shadow_analysis.freeze(row.user_id, league_id, pid, auction, values, listed.get(pid),
                            extra.get(pid, {}), debug.get("deadline"), opts.trailing_stop, now))
                        session.add(DecisionSnapshot(user_id=row.user_id, league_id=league_id, player_id=pid, auction=auction,
                                                     first_seen=now, last_changed=now, last_reason=values["reason"], **values))
                    elif old.last_reason != values["reason"]:
                        old.last_reason, old.last_changed = values["reason"], now
                        session.add(old)
                scope = (row.user_id, league_id)
                removed = 0
                if self._snapshots_pruned.get(scope) != day:
                    cutoff = now - timedelta(days=opts.snapshot_days)
                    removed = shadow_retention.archive_batch(session, *scope, cutoff)
                session.commit()
            if removed < shadow_retention.BATCH:
                self._snapshots_pruned[scope] = day
        except Exception:
            log.exception("Decision snapshots of league %s not stored", league_id)

    def _observe_forecasts(self, league_id: str, predicted: dict[str, tuple[int, int, int]], now: datetime) -> None:
        """E10.00: the forecast of every player of the round, once per league and market value day, and
        once a day what the value of earlier observations really did. Reads only stored data, never
        Kickbase. A failure here never stops a trading round."""
        day = analytics.market_value_day(now)
        seen = self._observed.setdefault((league_id, day), set())
        new = {pid: v for pid, v in predicted.items() if pid not in seen}
        settle = self._observations_settled.get(league_id) != day
        if not new and not settle:
            return
        try:
            with Session(self.engine) as session:
                if new:
                    stored = set(session.exec(select(ForecastObservation.player_id).where(
                        ForecastObservation.league_id == league_id, ForecastObservation.day == day,
                        ForecastObservation.player_id.in_(list(new)))).all())
                    for pid, (value, f1, f2) in new.items():
                        if pid not in stored and value > 0:
                            session.add(ForecastObservation(league_id=league_id, player_id=pid, day=day, observed_at=now,
                                                            value=value, forecast_1=f1, forecast_2=f2))
                if settle:
                    open_rows = session.exec(select(ForecastObservation).where(
                        ForecastObservation.league_id == league_id, ForecastObservation.resolved == False,  # noqa: E712
                        ForecastObservation.day < day)).all()
                    ids = list({r.player_id for r in open_rows})
                    histories = dict(session.exec(select(MarketValueHistory.player_id, MarketValueHistory.points).where(
                        MarketValueHistory.player_id.in_(ids))).all()) if ids else {}
                    for r in open_rows:
                        r.actual_1, r.actual_2, r.resolved = learning.settle_observation(histories.get(r.player_id) or [], r.day, r.value)
                        session.add(r)
                    session.exec(delete(ForecastObservation).where(
                        ForecastObservation.league_id == league_id, ForecastObservation.day < day - FORECAST_KEEP_DAYS))
                session.commit()
        except Exception:
            log.exception("Forecast observations of league %s not stored", league_id)
            return
        seen.update(new)
        if settle:
            self._observations_settled[league_id] = day
            ### Older days are not written again
            for key in [k for k in self._observed if k[0] == league_id and k[1] < day]:
                del self._observed[key]

    def forecast_quality(self, league_id: str) -> dict:
        """How good the market value forecast was on every observed player of the league (E10.00)."""
        with Session(self.engine) as session:
            rows = session.exec(select(
                ForecastObservation.value, ForecastObservation.forecast_1, ForecastObservation.forecast_2,
                ForecastObservation.actual_1, ForecastObservation.actual_2, ForecastObservation.day,
            ).where(ForecastObservation.league_id == league_id, ForecastObservation.actual_1.is_not(None))).all()
        quality = learning.forecast_quality([r[:5] for r in rows])
        days = [r[5] for r in rows]
        return {**quality, "observations": len(rows), "days": len(set(days)),
                "from_day": min(days, default=None), "to_day": max(days, default=None)}

    def _trades(self, session: Session, user_id: str, league_id: str) -> list[TradeLog]:
        since = utcnow() - timedelta(days=60)
        return list(
            session.exec(
                select(TradeLog).where(TradeLog.user_id == user_id, TradeLog.league_id == league_id, TradeLog.at >= since)
                .order_by(TradeLog.at, TradeLog.id)
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
                    details={"reason": action.reason, "name": action.name, "forecast_gain": action.forecast_gain,
                             "config_version": action.config_version, "collateral": _collateral_log(action)},
                )
            )
            session.commit()

    def _log_intent(self, league: League, user_id: str, action: Action) -> int:
        """Stored before the call: whatever happens next, the entry exists and is settled later."""
        with Session(self.engine) as session:
            entry = TradeLog(
                user_id=user_id, league_id=league.id, player_id=action.player_id, kind=action.kind, purpose=action.purpose,
                status="pending", price=action.price, market_value=action.market_value, points_gain=action.points_gain,
                details={"reason": action.reason, "name": action.name, "forecast_gain": action.forecast_gain,
                         "cost": action.cost, "for_player": action.for_player, "config_version": action.config_version,
                         "collateral": _collateral_log(action)},
            )
            session.add(entry)
            session.commit()
            return entry.id

    def _finish_entry(self, entry_id: int, status: str, error: str | None = None) -> None:
        with Session(self.engine) as session:
            entry = session.get(TradeLog, entry_id)
            if entry is None:
                return
            entry.status = status
            if status == "failed":
                entry.resolved_at = utcnow()
            if error:
                entry.details = {**entry.details, "error": error[:300]}
            session.add(entry)
            session.commit()

    def _finish_sale(self, league: League, user_id: str, entry_id: int, action: Action, received: int | None) -> None:
        """A confirmed sale. Profit only from known numbers: the proceeds Kickbase booked and the
        purchase price of this ownership (the won bid after the player's last sale, else the price the
        squad showed before the sale). Unknown stays unknown, never 0 €."""
        with Session(self.engine) as session:
            entry = session.get(TradeLog, entry_id)
            last_sale = session.exec(
                select(TradeLog.at).where(
                    TradeLog.user_id == user_id, TradeLog.league_id == league.id, TradeLog.player_id == action.player_id,
                    TradeLog.kind == "sell", TradeLog.status == "sold", TradeLog.id != entry_id,
                ).order_by(TradeLog.at.desc())
            ).first()
            query = select(TradeLog).where(
                TradeLog.user_id == user_id, TradeLog.league_id == league.id, TradeLog.player_id == action.player_id,
                TradeLog.kind == "bid", TradeLog.status == "won",
            )
            if last_sale is not None:
                query = query.where(TradeLog.at > last_sale)
            bought = session.exec(query.order_by(TradeLog.at.desc())).first()
            cost = (bought.paid if bought and bought.paid else None) or action.cost
            profit = received - cost if received is not None and cost is not None else None
            if entry is not None:
                entry.status, entry.resolved_at, entry.profit = "sold", utcnow(), profit
                entry.price = received if received is not None else action.price
                entry.details = {**entry.details, "received_known": received is not None, "cost": cost}
                session.add(entry)
            if bought is not None and bought.purpose == "profit" and profit is not None:
                with self._learning():
                    self._save_state(session, t.after_sale(t.Learned.load(load_state(session, STATE_KEY)), profit))
            session.commit()
        ### The sell ratio is learned from these events (sync.learning), only with booked proceeds
        if received is not None:
            self.automation.record(user_id, league.id, "sell", f"{action.name} sofort verkauft für {received / 1e6:.2f} Mio. €",
                                   details={"player_id": action.player_id, "market_value": action.market_value, "received": received})

    def _log_debug(self, league_id: str, user_id: str, data: dict) -> None:
        """Stored only when the decisions changed since the last round, so quiet hours cost nothing. The
        latest round is kept in memory for the dashboard either way."""
        self._latest[(league_id, user_id)] = (utcnow(), json.loads(json.dumps(data, default=str)))
        digest = hashlib.sha256(
            json.dumps([data.get("actions"), [(m["id"], m["decision"]) for m in data.get("market", [])]], default=str).encode()
        ).hexdigest()
        if self._last_debug.get((league_id, user_id)) == digest:
            return
        self._last_debug[(league_id, user_id)] = digest
        with Session(self.engine) as session:
            session.exec(delete(TraderDebug).where(TraderDebug.at < utcnow() - DEBUG_KEEP))
            session.add(TraderDebug(user_id=user_id, league_id=league_id, data=json.loads(json.dumps(data, default=str))))
            session.commit()

    def export(self, user_id: str, league_id: str, days: int) -> dict:
        """Everything to judge and tune the trader from outside: settings, what it learned, its trades,
        paper trades and the decisions of every changed round."""
        since = utcnow() - timedelta(days=days)
        with Session(self.engine) as session:
            row = session.get(UserAutomation, (user_id, league_id))
            learned, league_learned = self._load_states(session, league_id)
            trades = session.exec(
                select(TradeLog).where(TradeLog.user_id == user_id, TradeLog.league_id == league_id, TradeLog.at >= since).order_by(TradeLog.at)
            ).all()
            shadows = session.exec(select(ShadowTrade).where(ShadowTrade.league_id == league_id, ShadowTrade.user_id == user_id, ShadowTrade.at >= since).order_by(ShadowTrade.at)).all()
            events = session.exec(
                select(AutomationEvent)
                .where(AutomationEvent.user_id == user_id, AutomationEvent.league_id == league_id, AutomationEvent.at >= since)
                .order_by(AutomationEvent.at)
            ).all()
            rounds = session.exec(
                select(TraderDebug)
                .where(TraderDebug.user_id == user_id, TraderDebug.league_id == league_id, TraderDebug.at >= since)
                .order_by(TraderDebug.at)
            ).all()
            dump = lambda rows: [r.model_dump(mode="json") for r in rows]  # noqa: E731
            return {
                "about": EXPORT_ABOUT,
                "exported_at": utcnow().isoformat(),
                "league_id": league_id,
                "switches": {"trader": row.trader, "live": row.trader_live, "profit": row.trader_profit} if row else None,
                "options": t.Options.load(row.trader_options if row else None).__dict__,
                "flags": flags.load(row.trader_flags if row else None),
                "config": (lambda c: {"version": c.version, "created_at": c.created_at.isoformat(), "created_by": c.created_by,
                                      "data": c.data})(self.configs.active(user_id, league_id)),
                "option_limits": t.OPTION_LIMITS,
                "learned": learned.dump(),
                "learned_league": league_learned.dump(),
                "learned_effective": t.blend(learned, league_learned).dump(),
                "learned_limits": t.LEARNED_LIMITS,
                "constants": t.constants(),
                "forecast_quality": self.forecast_quality(league_id),
                "trades": dump(trades),
                "shadows": dump(shadows),
                "events": dump(events),
                "rounds": dump(rounds),
            }

    def import_tuning(self, user_id: str, league_id: str, options: dict | None, learned: dict | None) -> None:
        """Options for this league, merged into the current ones; learned values for all leagues. Both
        are clamped to their limits."""
        with Session(self.engine) as session:
            ### The values before go to the log: importing them back restores the old state
            before_row = session.get(UserAutomation, (user_id, league_id))
            before = {
                "options": t.Options.load(before_row.trader_options if before_row else None).__dict__,
                "learned": t.Learned.load(load_state(session, STATE_KEY)).dump(),
            }
        self.automation.record(
            user_id, league_id, "trader-import",
            "Autotrader-Werte importiert" + (" (inkl. gelernter Werte für alle Ligen)" if learned is not None else ""),
            details={"before": before, "options": options, "learned": learned},
        )
        with Session(self.engine) as session:
            if options is not None:
                row = session.get(UserAutomation, (user_id, league_id)) or UserAutomation(user_id=user_id, league_id=league_id)
                row.trader_options = t.Options.load({**t.Options.load(row.trader_options).__dict__, **options}).__dict__
                session.add(row)
                imported = t.Options.load(row.trader_options)
            if learned is not None:
                with self._learning():
                    current = t.Learned.load(load_state(session, STATE_KEY)).dump()
                    self._save_state(session, t.Learned.load({**current, **learned}))
                    session.commit()
            session.commit()
        if options is not None:
            self.configs.follow_options(user_id, league_id, imported, "import")

    def flags(self, user_id: str, league_id: str) -> dict:
        """The feature flags of this league: the stage set, the stage that applies, what each one does."""
        with Session(self.engine) as session:
            row = session.get(UserAutomation, (user_id, league_id))
        stored = flags.load(row.trader_flags if row else None)
        live = bool(row and row.trader_live)
        return {
            name: {"stage": stored[name], "effective": flags.effective(stored, name, live), "text": text}
            for name, text in flags.FLAGS.items()
        }

    def set_flags(self, user_id: str, league_id: str, changes: dict[str, str]) -> dict:
        """Sets validated flags (core.flags.validate first) and logs the stages before and after."""
        with Session(self.engine) as session:
            row = session.get(UserAutomation, (user_id, league_id)) or UserAutomation(user_id=user_id, league_id=league_id)
            before = flags.load(row.trader_flags)
            after = {**before, **changes}
            row.trader_flags = after
            session.add(row)
            session.commit()
        changed = {name: [before[name], after[name]] for name in after if before[name] != after[name]}
        if changed:
            self.automation.record(
                user_id, league_id, "trader-flags",
                "Feature Flags geändert: " + ", ".join(f"{n} {a} → {b}" for n, (a, b) in changed.items()),
                details={"before": before, "after": after},
            )
        return self.flags(user_id, league_id)

    def rejection_stats(self, user_id: str, league_id: str) -> dict:
        """E01.03: why market players were not bought over 1, 7 and 21 days, once per player, day and
        code. The stored rounds are only read again when a new one was logged."""
        with Session(self.engine) as session:
            newest = session.exec(select(TraderDebug.id).where(
                TraderDebug.user_id == user_id, TraderDebug.league_id == league_id).order_by(TraderDebug.id.desc())).first()
            cached = self._rejections.get((league_id, user_id))
            if cached is not None and cached[0] == newest:
                return cached[1]
            since = utcnow() - timedelta(days=max(rc.WINDOWS))
            rows = session.exec(select(TraderDebug.at, TraderDebug.data).where(
                TraderDebug.user_id == user_id, TraderDebug.league_id == league_id, TraderDebug.at >= since)).all()
        stats = rc.rejection_stats(list(rows), utcnow(), _local_day)
        self._rejections[(league_id, user_id)] = (newest, stats)
        return stats

    def dashboard(self, user_id: str, league_id: str) -> dict:
        """The trader's state now (from its latest round) and its statistics, for the dashboard."""
        latest = self._latest.get((league_id, user_id))
        if latest is None:
            with Session(self.engine) as session:
                row = session.exec(
                    select(TraderDebug).where(TraderDebug.user_id == user_id, TraderDebug.league_id == league_id).order_by(TraderDebug.at.desc())
                ).first()
            latest = (row.at, row.data) if row else None
        stats = self._stats(user_id, league_id)
        if latest is None:
            return {"at": None, "stats": stats}
        at, d = latest
        names = {p["id"]: p.get("name") for p in [*d.get("squad", []), *d.get("pending", []), *d.get("market", [])]}
        protections = [
            label for active, label in (
                (d.get("keep_starters"), "Startelf gesperrt (Anpfiff naht oder keine automatische Aufstellung)"),
                (d.get("keep_starters") and not d.get("lineup_known", True), "Aufstellung nicht lesbar: alle fitten Spieler gesperrt"),
                (d.get("paused"), "Wochen-Stop-Loss: Gewinnhandel pausiert"),
                (d.get("forecast_paused"), "Prognose unzuverlässig: Gewinnhandel pausiert"),
                (d.get("phase") in ("prepare", "repay", "final"), "Spieltag naht: Ersatz vor Gewinnhandel, Kreditgrenzen"),
                (d.get("phase") == "final", "Letzte Stunde: keine Gewinn-Gebote, kein Kredit"),
                (d.get("credit_mode") == 0, "Kein Kredit"),
                (d.get("reserve"), "Reserve wird nie ausgegeben"),
            ) if active
        ]
        ### The candidates worth explaining: bids first, then the best net return, then the rest
        market = sorted(
            d.get("market", []),
            key=lambda m: (not str(m.get("decision", "")).split(": ", 1)[-1].startswith("Gebot"), -(m.get("net_at_low") or -10**12)),
        )[:15]
        return {
            "at": at,
            "live": d.get("live"),
            "phase": d.get("phase"),
            "deadline": d.get("deadline"),
            "repay_from": d.get("repay_from"),
            "budget": d.get("budget"),
            "open_bids": sum((d.get("open_bids") or {}).values()),
            "cash_free": d.get("cash_free"),
            "credit": d.get("credit"),
            "credit_mode": d.get("credit_mode"),
            "liquidation": d.get("liquidation"),
            "money_check": d.get("money_check"),
            "forecast_quality": self.forecast_quality(league_id),
            "rejections": self.rejection_stats(user_id, league_id),
            "reason_texts": rc.TEXT,
            "worst_case": d.get("worst_case"),
            "profit_room": d.get("profit_room"),
            "gaps_confirmed": d.get("gaps_confirmed"),
            "gaps_projected": d.get("gaps_projected"),
            "unrealized": d.get("unrealized"),
            "week_profit": d.get("week_profit"),
            "positions": [{"player_id": pid, "name": names.get(pid), **v} for pid, v in (d.get("positions") or {}).items()],
            "protections": protections,
            "candidates": [
                {k: m.get(k) for k in ("id", "name", "pos", "value", "price", "bid_low", "net_at_low", "p_win_at_low", "expected",
                                       "ahead", "samples", "quality", "forecast", "gain", "money", "decision")}
                for m in market
            ],
            "blocked": d.get("risk_blocked", []),
            "actions": d.get("actions", []),
            "runtime_ms": d.get("runtime_ms"),
            "stats": stats,
        }

    def _stats(self, user_id: str, league_id: str) -> dict:
        """Since the start: realized net (known profits only, unknown ones counted apart), per purpose,
        auctions, markup, holding time, return per euro and day, blocked trades and matchdays at risk."""
        with Session(self.engine) as session:
            rows = list(session.exec(select(TradeLog).where(TradeLog.user_id == user_id, TradeLog.league_id == league_id).order_by(TradeLog.at)))
            week_rounds = session.exec(
                select(TraderDebug.data).where(TraderDebug.user_id == user_id, TraderDebug.league_id == league_id,
                                               TraderDebug.at >= utcnow() - timedelta(days=7))
            ).all()
            debts = session.exec(
                select(AutomationEvent.key).where(AutomationEvent.user_id == user_id, AutomationEvent.league_id == league_id,
                                                  AutomationEvent.key.like("trader-debt:%"))
            ).all()
        real = [r for r in rows if r.status not in ("planned", "failed")]
        sells = [r for r in real if r.kind == "sell" and r.status == "sold"]
        known = [r for r in sells if r.profit is not None]
        won = [r for r in real if r.kind == "bid" and r.status == "won"]
        lost = [r for r in real if r.kind == "bid" and r.status == "lost"]
        holds, capital_days = [], 0
        for s in known:
            bought = next((b for b in reversed(won) if b.player_id == s.player_id and (b.resolved_at or b.at) <= s.at), None)
            if bought is not None:
                days = max((s.at - (bought.resolved_at or bought.at)).days, 1)
                holds.append(days)
                capital_days += (bought.paid or bought.price) * days
        purposes: dict[str, dict] = {}
        for s in sells:
            p = purposes.setdefault(s.purpose, {"sales": 0, "profit": 0, "unknown": 0})
            p["sales"] += 1
            if s.profit is None:
                p["unknown"] += 1
            else:
                p["profit"] += s.profit
        markups = [(b.paid or b.price) / b.market_value - 1 for b in won if b.market_value]
        blocked = {(b["player_id"], b["code"]) for d in week_rounds for b in (d or {}).get("risk_blocked", [])}
        return {
            "realized": sum(r.profit for r in known),
            "sales": len(sells),
            "unknown_profits": len(sells) - len(known),
            "data_completeness": round(len(known) / len(sells), 2) if sells else None,
            "by_purpose": purposes,
            "auctions_won": len(won),
            "auctions_lost": len(lost),
            "win_rate": round(len(won) / (len(won) + len(lost)), 2) if won or lost else None,
            "avg_markup": round(sum(markups) / len(markups), 4) if markups else None,
            "avg_hold_days": round(sum(holds) / len(holds), 1) if holds else None,
            "return_per_euro_day": round(sum(r.profit for r in known) / capital_days, 6) if capital_days else None,
            "blocked_this_week": len(blocked),
            "matchdays_at_risk": len(set(debts)),
            "matchdays_rescued": len({r.at.date() for r in sells if r.purpose == "rescue"}),
        }

    def backtest(self, league: League, user_id: str, capital: int, folds: int) -> dict:
        """The profit trading strategies replayed on this league's real auctions (core.backtest)."""
        from api.insights import Insights
        from api.routes import analysis_limits
        from core import backtest

        with Session(self.engine) as session:
            membership = session.get(UserLeague, (user_id, league.id))
            max_squad, max_club = analysis_limits(self.settings, membership)
            history = Insights(session, league, user_id, self.automation.model, max_squad, max_club).auctions()
            ids = list({pid for _, pid, _, _ in history})
            histories = dict(
                session.exec(select(MarketValueHistory.player_id, MarketValueHistory.points).where(MarketValueHistory.player_id.in_(ids))).all()
            )
            context = load_context(session, league.competition_id, ids, utcnow())
            row = session.get(UserAutomation, (user_id, league.id))
            ratio = t.sell_ratio(t.Options.load(row.trader_options if row else None), learned_sell_ratio(session))
        auctions = [backtest.Auction(analytics.market_value_day(at), pid, price, value) for at, pid, price, value in history if value > 0]
        matches = {pid: context.match_points(pid) for pid in ids}
        return backtest.run(auctions, histories, matches, capital, ratio, folds)

    def reset_learning(self, user_id: str, league_id: str, scope: str) -> dict:
        """Back to the starting values: `global` (the base model, all leagues) or `league` (this
        league's bid heights). The values before go to the log, an import restores them."""
        key = STATE_KEY if scope == "global" else f"{STATE_KEY}:{league_id}"
        with self._learning(), Session(self.engine) as session:
            before = t.Learned.load(load_state(session, key)).dump()
            self._save_state(session, t.Learned(), key)
            session.commit()
        self.automation.record(user_id, league_id, "trader-import", f"Gelerntes zurückgesetzt ({scope})", details={"before": before, "scope": scope})
        return before

    def _notify(self, league_id: str, user_id: str, debug: dict, stage: str, deadline: datetime | None, now: datetime) -> None:
        """Pushes that need the user, each once per period (deduplicated by key): the eleven has gaps
        close to a matchday (once per deadline), the stop-loss paused profit trading (once per week),
        the forecast is unreliable (once per day). The rest (trades, unclear status, debt, automatic
        pause, login) is pushed where it happens."""
        day = now.astimezone(analytics.MARKET_VALUE_TIMEZONE).date().isoformat()
        notes = []
        gaps = debug.get("gaps_confirmed", 0)
        if gaps and stage in ("prepare", "repay", "final") and deadline is not None:
            projected = debug.get("gaps_projected", gaps)
            notes.append((f"trader-gaps:{league_id}:{user_id}:{deadline.isoformat()}", "Autotrader: Startelf unvollständig",
                          f"{gaps} Platz/Plätze der Startelf leer vor dem Spieltag"
                          + (f", mit allen offenen Geboten noch {projected}" if projected != gaps else "")))
        if debug.get("paused"):
            notes.append((f"trader-stoploss:{league_id}:{user_id}:{t.week_of(now)}", "Autotrader: Stop-Loss",
                          "Gewinnhandel pausiert bis Wochenende: Wochenverlust hat das Limit erreicht"))
        if debug.get("forecast_paused"):
            notes.append((f"trader-forecast:{league_id}:{user_id}:{day}", "Autotrader: Prognose unzuverlässig",
                          "Gewinnhandel pausiert, bis die Marktwertprognose wieder trifft"))
        for key, title, message in notes:
            if not self.automation._has_key(key):
                self.automation.record(user_id, league_id, "trader", message, ok=False, key=key)
                self._pushes.append((user_id, title, message, f"trader-note-{league_id}"))

    def _warn_debt(self, league: League, user_id: str, budget: int, deadline: datetime) -> None:
        """Once per matchday: the bench cannot cover the debt, the user has to decide what goes."""
        key = f"trader-debt:{league.id}:{user_id}:{deadline.isoformat()}"
        if self.automation._has_key(key):
            return
        message = f"Minus von {-budget / 1e6:.2f} Mio. € lässt sich nicht ganz ausgleichen – bitte vor dem Anpfiff selbst verkaufen"
        self.automation.record(user_id, league.id, "trader", message, ok=False, key=key)
        self._pushes.append((user_id, "Autotrader: Minus", message, f"trader-debt-{league.id}"))

    def _log_planned(self, league: League, user_id: str, action: Action, now: datetime) -> None:
        """Dry run: logged and pushed once per player, kind and day."""
        key = f"trader:{league.id}:{user_id}:{action.kind}:{action.player_id}:{now.astimezone(analytics.MARKET_VALUE_TIMEZONE).date()}"
        if self.automation._has_key(key):
            return
        if action.kind != "withdraw":
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
                session.exec(select(ShadowTrade).where(ShadowTrade.league_id == league_id, ShadowTrade.user_id == user_id).order_by(ShadowTrade.at.desc()))
            )
            names = dict(
                session.exec(select(Player.id, Player.last_name).where(Player.id.in_([s.player_id for s in shadows[:30]]))).all()
            )
            state = t.blend(*self._load_states(session, league_id))
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
                "direction_rate": state.direction_rate,
                "forecast_paused": bool(state.forecast_pause),
            },
            "paused": bool(current and opts.stop_loss > 0 and current["profit"] <= -opts.stop_loss),
            "pause_reason": self._pause_reason(user_id, league_id),
            "enabled_on_server": self.settings.automation.trader,
        }

    def _pause_reason(self, user_id: str, league_id: str) -> str | None:
        """The latest automatic live pause of the last hour, for the page."""
        with Session(self.engine) as session:
            event = session.exec(
                select(AutomationEvent).where(
                    AutomationEvent.user_id == user_id, AutomationEvent.league_id == league_id,
                    AutomationEvent.kind == "trader-pause", AutomationEvent.at >= utcnow() - timedelta(hours=1),
                ).order_by(AutomationEvent.at.desc())
            ).first()
        return event.message if event else None


def _price(
    c: t.Candidate, purpose: str, upgrade: t.Upgrade | None, extra: float, money: int, opts: t.Options, state: t.Learned,
    ratio: float, profit_room: int, shares: list[tuple[int, float]] | None = None, use_ev: bool = True,
) -> int | None:
    """The bid for `c`, never above the smallest limit (money, cover price, the net profit cap, the
    price per point), None when even the minimum bid breaks one.

    With enough won auctions in the league: the bid with the highest expected value P(win) x (worth
    - bid), where worth is the net sale proceeds (profit), the fair price of the points gained
    (eleven) or the cover price (substitute). Otherwise the learned height between low and high."""
    caps = [money if purpose == "profit" else int(money * opts.lineup_share / 100)]
    worth = opts.cover_max_price
    if purpose == "cover":
        caps.append(opts.cover_max_price)
    if purpose == "profit":
        caps += [profit_room, t.max_profit_bid(c, ratio, state.min_margin, opts.min_roi / 100)]
        worth = t.expected_proceeds(c, ratio)
    if upgrade is not None:
        worth = int(upgrade.replaced_value * ratio + opts.max_cost_per_point * max(upgrade.gain, 0.1))
        caps.append(worth)
    ### A bid a player was sold for wants a high chance, not the best value: there the height decides
    chosen = t.best_bid(c, worth, min(caps), t.winning_markups(shares or [], c.value)) if use_ev else None
    bid = chosen[0] if chosen else t.bid_for(c, extra, min(caps))
    if bid is None:
        return None
    if purpose == "profit" and not t.is_profit_buy(c, bid, state.min_margin, ratio, opts.min_roi / 100):
        return None
    if upgrade is not None and not t.worth_it(upgrade, bid, opts, ratio):
        return None
    return bid


def _collateral_log(action: Action) -> list[dict]:
    """The sales a bid counts on, for the trade log: later rounds read them so none is counted twice."""
    return [{"player_id": c.player_id, "kind": c.kind, "value": c.value, "sell_until": c.sell_until.isoformat()} for c in action.collateral]


def _local_day(at: datetime) -> int:
    """The Berlin calendar day of a moment, as a number, for counting once per day."""
    return at.astimezone(analytics.MARKET_VALUE_TIMEZONE).date().toordinal()


def _reason_fields(found: list[str] | None, upgrade_code: str | None) -> dict:
    """Primary and secondary reason codes of a market player for the debug log. Why he is no lineup
    upgrade is always among the secondary ones, unless a bid is planned."""
    found = list(found or [rc.NOT_CHECKED])
    if upgrade_code and upgrade_code not in found and found[0] != rc.BID_PLANNED:
        found.append(upgrade_code)
    return {"reason": found[0], "reasons": found[1:]}


def _auction(base: t.Learned, local: t.Learned, value: int, won: bool, own: int, winner: int | None,
             weight: float = 1.0) -> tuple[t.Learned, t.Learned]:
    """An auction teaches the global base and the league it happened in."""
    return (t.after_auction(base, value, won, own, winner, weight), t.after_auction(local, value, won, own, winner, weight))


def _purpose_rank(purpose: str) -> int:
    """Which bid goes first when money is short: profit trades, then substitutes, the eleven last."""
    return {"profit": 0, "cover": 1}.get(purpose, 2)


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
    if action.kind == "withdraw":
        return "Gebot zurückziehen"
    return f"für {action.price / 1e6:.2f} Mio. € bieten" if action.kind == "bid" else "verkaufen"
