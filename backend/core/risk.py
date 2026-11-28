"""The autotrader's risk engine: validates every planned action on its own, independent of why the
strategy wants it. A score never overrides a rule here. Used for live rounds and dry runs alike.

Actions are checked in plan order with running totals (money, squad, clubs, limits), so a plan as a
whole stays within the rules, also if every open auction is won. Planned sales are no money: a bid
that needs a sale's proceeds waits for the next round, after the sale is confirmed.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from core import coach, finance
from core import trader as t

### Reason codes, stable for logs, exports and tests
KILL_SWITCH = "KILL_SWITCH" # Server, league or trader switch off
BID_INVALID = "BID_INVALID" # No price, zero, or below the minimum bid
AUCTION_EXPIRED = "AUCTION_EXPIRED"
AUCTION_UNKNOWN = "AUCTION_UNKNOWN" # No end time: no profit bid
NOT_LISTED = "NOT_LISTED"
OVER_BUDGET = "OVER_BUDGET" # Worst case (every open bid won) below reserve minus allowed credit
SQUAD_FULL = "SQUAD_FULL"
CLUB_FULL = "CLUB_FULL"
DAILY_BIDS = "DAILY_BIDS"
DAILY_SALES = "DAILY_SALES"
BLOCKED = "BLOCKED" # Rebuy block or an unsettled earlier call for this player
PROFIT_NEGATIVE = "PROFIT_NEGATIVE" # Net profit after the sale ratio below margin or return
PHASE = "PHASE" # Not allowed this close to the deadline
NOT_OWNED = "NOT_OWNED"
LOCKED = "LOCKED"
STARTER = "STARTER" # Fit player of the best eleven
BREAKS_COVER = "BREAKS_COVER"
NEW_GAP = "NEW_GAP" # The eleven would get an empty slot
MANUAL_BID = "MANUAL_BID" # Never touched
NOT_OPEN = "NOT_OPEN"
ACTION_INVALID = "ACTION_INVALID"
UNCONFIRMED_ACTION = "UNCONFIRMED_ACTION"
FINANCE_COLLATERAL_TAKEN = "FINANCE_COLLATERAL_TAKEN" # The sale is already counted for another bid (E04.06)
FINANCE_PLAN_INVALID = "FINANCE_PLAN_INVALID" # The claimed sale does not hold when checked again (E04.10)


class Planned(Protocol):
    kind: str
    purpose: str
    player_id: str
    price: int


@dataclass
class Context:
    now: datetime
    switches_on: bool
    deadline: datetime | None
    budget: int
    reserve: int
    credit: int # Overdraft the simulated liquidation covers
    credit_mode: int
    open_bids: dict[str, int] # Every own open bid, manual and trader, after planned withdrawals
    trader_bids: set[str]
    squad: list[t.Candidate] # Confirmed squad, with in_best and locked
    listings: dict[str, t.Candidate] # Market players by id
    club_of: dict[str, str | None] # Club of every player above
    max_squad: int
    max_club: int
    bids_left: int
    sales_left: int
    blocked: set[str] = field(default_factory=set)
    ratio: float = 0.9
    min_margin: int = 0
    min_roi: float = 0.0
    rescue_override: bool = False
    unconfirmed: bool = False
    bench: int = t.BENCH_FULL # The bench the planning keeps (E05.02), full unless the flag allows less
    ### E04.04/E04.05: sales a bid counts on once it is won, by the player bid on; players already
    ### counted for open bids of earlier rounds; the start of the repay phase they have to be sold by
    collateral: dict[str, list[finance.Collateral]] = field(default_factory=dict)
    used_collateral: set[str] = field(default_factory=set)
    repay_from: datetime | None = None


def credit_for(purpose: str, expires_at: datetime | None, ctx_phase: str, deadline: datetime | None, credit: int, mode: int) -> int:
    """The overdraft a bid may use. None for profit trades unless mode 2, none close to the deadline,
    none for auctions ending inside the repay window."""
    if mode <= 0 or ctx_phase == "final":
        return 0
    if purpose == "profit" and (mode < 2 or ctx_phase in ("prepare", "repay")):
        return 0
    if ctx_phase == "repay" and deadline is not None and (expires_at is None or expires_at <= deadline):
        return 0
    return credit


def validate(actions: Sequence[Planned], ctx: Context) -> list[str | None]:
    """A reason code per action, None where it may run. Rejected actions do not change the totals."""
    phase = t.phase(ctx.now, ctx.deadline)
    squad = list(ctx.squad)
    open_bids = dict(ctx.open_bids)
    new_bids: dict[str, int] = {}
    clubs = Counter(ctx.club_of.get(p.player_id) for p in squad)
    clubs.update(ctx.club_of.get(pid) for pid in open_bids)
    bids_left, sales_left = ctx.bids_left, ctx.sales_left
    results: list[str | None] = []
    ### Approved conditional financing so far: money it adds, players it uses (each at most once)
    extra = 0
    used = set(ctx.used_collateral)

    for action in actions:
        reason = None if ctx.switches_on else KILL_SWITCH
        if reason is None and ctx.unconfirmed and (action.kind == "bid" or action.purpose == "room"):
            reason = UNCONFIRMED_ACTION
        if reason is None and action.kind == "bid":
            claims = ctx.collateral.get(action.player_id, [])
            reason = _bid(action, ctx, phase, squad, open_bids, new_bids, clubs, bids_left, extra + sum(c.value for c in claims))
            if reason is None and claims:
                reason = _collateral(claims, ctx, squad, used)
            if reason is None and claims:
                extra += sum(c.value for c in claims)
                used.update(c.player_id for c in claims)
            if reason is None:
                new_bids[action.player_id] = action.price
                clubs[ctx.club_of.get(action.player_id)] += 1
                bids_left -= 1
        elif reason is None and action.kind == "sell":
            reason = _sell(action, ctx, squad, sales_left)
            if reason is None:
                squad = [p for p in squad if p.player_id != action.player_id]
                if action.purpose != "rescue":
                    sales_left -= 1
        elif reason is None and action.kind == "withdraw":
            if action.player_id not in ctx.trader_bids:
                reason = MANUAL_BID
            elif action.player_id not in open_bids:
                reason = NOT_OPEN
            else:
                open_bids.pop(action.player_id)
                clubs[ctx.club_of.get(action.player_id)] -= 1
        elif reason is None:
            reason = ACTION_INVALID
        results.append(reason)
    return results


def _collateral(claims: list[finance.Collateral], ctx: Context, squad: list[t.Candidate], used: set[str]) -> str | None:
    """Each claimed sale on its own: not counted twice, and it holds when rebuilt from the confirmed squad."""
    for c in claims:
        if c.player_id in used or sum(1 for o in claims if o.player_id == c.player_id) > 1:
            return FINANCE_COLLATERAL_TAKEN
        error = finance.check_collateral(c, squad, ctx.listings.get(c.bid_for), ctx.ratio, ctx.bench, ctx.now, ctx.repay_from)
        if error:
            return error
    return None


def _bid(action: Planned, ctx: Context, phase: str, squad: list[t.Candidate], open_bids: dict[str, int],
         new_bids: dict[str, int], clubs: Counter, bids_left: int, conditional: int = 0) -> str | None:
    target = ctx.listings.get(action.player_id)
    if target is None:
        return NOT_LISTED
    if action.player_id in ctx.blocked or action.player_id in open_bids or action.player_id in new_bids:
        return BLOCKED
    if action.price <= 0 or action.price < max(target.bid_low, target.price, target.value) or action.price % coach.BID_STEP:
        return BID_INVALID
    if target.expires_at is not None and target.expires_at <= ctx.now:
        return AUCTION_EXPIRED
    profit = action.purpose == "profit"
    if profit and target.expires_at is None:
        return AUCTION_UNKNOWN
    if profit and (phase == "final" or (phase == "repay" and ctx.deadline is not None and target.expires_at <= ctx.deadline)):
        return PHASE
    if bids_left <= 0:
        return DAILY_BIDS
    if len(squad) + len(open_bids) + len(new_bids) + 1 > ctx.max_squad:
        return SQUAD_FULL
    if clubs[ctx.club_of.get(action.player_id)] + 1 > ctx.max_club and ctx.club_of.get(action.player_id) is not None:
        return CLUB_FULL
    ### Worst case: every open and new bid is won. Planned sales bring nothing yet
    allowed = credit_for(action.purpose, target.expires_at, phase, ctx.deadline, ctx.credit, ctx.credit_mode) + conditional
    worst = ctx.budget - sum(open_bids.values()) - sum(new_bids.values()) - action.price
    if worst < ctx.reserve - allowed:
        return OVER_BUDGET
    if profit and not t.is_profit_buy(target, action.price, ctx.min_margin, ctx.ratio, ctx.min_roi):
        return PROFIT_NEGATIVE
    return None


def _sell(action: Planned, ctx: Context, squad: list[t.Candidate], sales_left: int) -> str | None:
    player = next((p for p in squad if p.player_id == action.player_id), None)
    if player is None:
        return NOT_OWNED
    if action.player_id in ctx.blocked:
        return BLOCKED
    rescue = action.purpose == "rescue"
    if player.locked and player.fit and not (rescue and ctx.rescue_override):
        return LOCKED
    if rescue:
        return None # Only the switch and ownership: a negative balance costs the whole matchday
    if sales_left <= 0:
        return DAILY_SALES
    if player.fit and player.in_best:
        return STARTER
    if not t.keeps_cover(squad, player, ctx.bench):
        return BREAKS_COVER
    rest = [p for p in squad if p is not player]
    if t.best_of(rest).empty_slots > t.best_of(squad).empty_slots:
        return NEW_GAP
    return None


def explain(codes: Iterable[str | None]) -> dict[str, int]:
    """How many actions each reason blocked, for the round's log."""
    return dict(Counter(code for code in codes if code))
