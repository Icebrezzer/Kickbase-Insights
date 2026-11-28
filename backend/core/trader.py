"""The autotrader's decisions. Pure functions, the acting part is `sync/trader.py`.

Three goals, one market:
- Starting eleven: a market player is bought for the eleven only when he raises its expected points by
  at least `min_gain`, plays regularly, beats the player he pushes out in season average (by
  `min_avg_edge`) and in recent form, and the extra money per extra point stays within
  `max_cost_per_point`.
- Bench cover: a cheap fit player for a position without a substitute.
- Profit between matchdays: players whose market value is forecast to rise more than the bid costs on
  top of the value. Sold again once the forecast turns.

Sales follow one order: unavailable players first, then players who rarely start, then the bench by
the weakest daily rise. A sale never leaves a position without a fit substitute.

Shadow trades are the same decisions on paper: what the trader did not do (limits, money, slots) is
followed anyway, and what really happened after a sale is watched. They teach the bid height, the
forecast's reliability and how much more a swap target has to rise.
"""

from __future__ import annotations

import contextlib
import math
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, fields, replace
from datetime import datetime, timedelta

from core import analytics, coach

### Profit buys are judged on the forecast of the next this many market value updates
PROFIT_HOLD = 2
### A sold player is watched this many market value updates afterwards
REGRET_DAYS = 3
### Never buy back a player the trader sold within this time
REBUY_BLOCK = timedelta(days=7)
### Own purchases are kept at least this long, unless they got injured
MIN_HOLD = timedelta(hours=20)
### Starters can be sold again this long after the first kick-off of a matchday
KICKOFF_GRACE = timedelta(minutes=5)
### When a player is sold to make room, the bid is placed at least this far towards the safe bid
ROOM_EXTRA = 0.6


### ===============================================================================
### Options, per league in the user's settings
### ===============================================================================


@dataclass(frozen=True)
class Options:
    min_gain: float = 2.0 # Expected points the eleven gains at least
    max_cost_per_point: int = 300_000 # Bid above the replaced player's value per gained point
    min_avg_edge: int = 10 # Season average above the replaced player's, in percent
    min_play: int = 60 # Share of the club's last five matches a target played, in percent
    lineup_share: int = 100 # Share of the free budget a lineup bid may use, in percent
    profit_share: int = 60 # ... a profit bid
    reserve: int = 0 # Money that is never spent
    cover_max_price: int = 3_000_000 # Most a substitute for an uncovered position may cost
    snapshot_limit: int = 32
    daily_bids: int = 6
    daily_sales: int = 3
    stop_loss: int = 3_000_000 # Realized weekly loss that pauses the profit trading
    sell_window: int = 20 # Minutes before an auction ends when a player is sold to make room
    starter_lock: int = 60 # Minutes before the first kick-off from which starters are kept
    min_roi: float = 2.0 # Net return a profit buy must make at least, in percent of the bid
    credit_mode: int = 1 # 0: never on credit, 1: only for the eleven and substitutes, 2: also profit trades
    trailing_stop: int = 5 # Percent below the peak since the purchase that sells a position in profit, 0 off
    position_stop: int = 10 # Percent net loss on the purchase price that sells a position, 0 off
    max_hold_days: int = 7 # Days a profit position may be held without enough left to gain, 0 off
    shadow: bool = True # Learn from paper trades too
    rescue_override: bool = False # Rescue sales may also sell locked players (starters, fresh buys)
    ### Percent of the market value an instant sale to Kickbase brings. Kickbase pays the full market value
    ### (100, confirmed by the user 27.11.2026); 90 keeps the cautious assumption of before as default
    sell_ratio: int = 90
    ### A target that changes the formation and pushes a player of another position out is judged by the
    ### points (next matchday, next three matches), not by that other player's season quality (E05.08)
    upgrade_cross_position: bool = False
    ### Bench strategy (E05.02), only with the flag flexible_bench: 0 full, 1 minimal, 2 none between matchdays
    bench_strategy: int = 0

    @classmethod
    def load(cls, data: dict | None) -> Options:
        """Unknown keys are dropped, every value is clamped, junk keeps the default: the stored JSON
        is not trusted. Booleans accept true/false, 1/0 and their strings only ("false" is False)."""
        data = data if isinstance(data, dict) else {}
        values = {}
        for f in fields(cls):
            if f.name not in data or data[f.name] is None:
                continue
            raw = data[f.name]
            if f.name in BOOL_OPTIONS:
                flag = parse_bool(raw)
                if flag is not None:
                    values[f.name] = flag
                continue
            number = parse_number(raw)
            if number is None:
                continue
            low, high = OPTION_LIMITS[f.name]
            number = min(max(number, low), high)
            values[f.name] = number if f.name in ("min_gain", "min_roi") else int(number)
        return cls(**values)


BOOL_OPTIONS = ("shadow", "rescue_override", "upgrade_cross_position")

### Strategy profiles: starting points the user can apply and then adjust. Hard limits (risk engine,
### OPTION_LIMITS) hold for every profile. Values are proposals until the backtest calibrates them
PROFILES: dict[str, dict[str, float | int | bool]] = {
    "conservative": {
        "min_gain": 5.0, "max_cost_per_point": 250_000, "min_avg_edge": 15, "min_play": 70, "lineup_share": 80,
        "profit_share": 30, "reserve": 2_000_000, "min_roi": 2.0, "credit_mode": 1, "daily_bids": 6, "daily_sales": 3,
        "stop_loss": 1_500_000, "trailing_stop": 4, "position_stop": 6, "max_hold_days": 5, "sell_window": 15,
    },
    "balanced": {},
    "aggressive": {
        "min_gain": 1.5, "max_cost_per_point": 400_000, "min_avg_edge": 5, "min_play": 50, "lineup_share": 100,
        "profit_share": 80, "reserve": 0, "min_roi": 1.0, "credit_mode": 2, "daily_bids": 10, "daily_sales": 5,
        "stop_loss": 5_000_000, "trailing_stop": 8, "position_stop": 15, "max_hold_days": 10, "sell_window": 30,
    },
}


def profile(name: str) -> Options:
    """A profile on top of the defaults ("balanced" are the defaults), validated like any import."""
    return Options.load({**Options().__dict__, **PROFILES[name]})


def parse_bool(raw: object) -> bool | None:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)) and raw in (0, 1):
        return bool(raw)
    if isinstance(raw, str) and raw.strip().lower() in ("true", "false", "1", "0"):
        return raw.strip().lower() in ("true", "1")
    return None


def parse_number(raw: object) -> float | None:
    """A finite number, or None. Booleans are no numbers here, NaN and infinity are refused."""
    if isinstance(raw, bool):
        return None
    try:
        number = float(raw) # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


OPTION_LIMITS: dict[str, tuple[float, float]] = {
    "min_gain": (0.0, 100.0),
    "max_cost_per_point": (0, 50_000_000),
    "min_avg_edge": (0, 200),
    "min_play": (0, 100),
    "lineup_share": (10, 100),
    "profit_share": (10, 100),
    "reserve": (0, 500_000_000),
    "cover_max_price": (0, 50_000_000),
    "snapshot_limit": (1, 200),
    "daily_bids": (0, 30),
    "daily_sales": (0, 30),
    "stop_loss": (0, 100_000_000),
    "sell_window": (5, 180),
    "starter_lock": (0, 24 * 60),
    "min_roi": (0.0, 100.0),
    "credit_mode": (0, 2),
    "trailing_stop": (0, 50),
    "position_stop": (0, 100),
    "max_hold_days": (0, 60),
    "sell_ratio": (50, 100),
    "bench_strategy": (0, 2),
}


def sell_ratio(opts: Options, learned: float | None) -> float:
    """The instant sale ratio the trader counts on: the league's setting, a learned one only ever lowers it."""
    setting = opts.sell_ratio / 100
    return min(learned or setting, setting)


### ===============================================================================
### Players
### ===============================================================================


@dataclass(frozen=True)
class Candidate:
    """A player of the own squad or of the market, with everything the decisions weigh."""
    player_id: str
    position: int
    expected: float # Next matchday
    average: float | None # Season average points
    form: float | None # Weighted points of the last (up to five) matches he played
    play: float | None # Share of the club's last five matches he was part of
    fit: bool
    today: int # Market value change of the latest update
    forecast: int # Forecast change of the next update
    gain: int # Forecast change over the next PROFIT_HOLD updates, scaled by what the forecast is worth
    value: int
    team_id: str | None = None
    ahead: float | None = None # Mean expected points over the next three matches, None when unknown
    samples: int | None = None # Matches played of the club's last five: how much data form and play rest on
    ### Squad only
    in_best: bool = False
    locked: bool = False # Bought by the trader too recently, or a starter before the kick-off
    ### Market only
    price: int = 0
    bid_low: int = 0
    bid_high: int = 0
    expires_at: datetime | None = None

    def regular(self, min_play: float) -> bool:
        """Without data a squad player counts as one: nobody is sold for missing numbers."""
        return self.play is None or self.play >= min_play


def best_of(squad: Sequence[Candidate]) -> coach.Eleven:
    return coach.best_eleven([coach.LineupCandidate(p.player_id, p.position, p.expected, p.value) for p in squad])


### How much bench the squad keeps (E05.02). FULL is the rule of 2.0 and the default everywhere:
### every position has a fit player beyond the best eleven. MINIMAL: a second fit goalkeeper and one fit
### field player beyond the eleven, of any position (a formation change covers the others). NONE: no bench
BENCH_FULL, BENCH_MINIMAL, BENCH_NONE = 0, 1, 2
### The league option `bench_strategy`: 0 full, 1 minimal, 2 none between matchdays (full from 24 hours before)
BENCH_STRATEGIES = {0: "volle Absicherung", 1: "minimal", 2: "keine außerhalb der Spieltagsnähe"}


def bench_mode(strategy: int, stage: str) -> int:
    """The bench mode of a league's strategy in a deadline phase: close to the matchday the eleven has to
    be safe, so strategy 2 keeps the full bench in prepare, repay and final."""
    if strategy == 1:
        return BENCH_MINIMAL
    if strategy == 2:
        return BENCH_FULL if stage in ("prepare", "repay", "final") else BENCH_NONE
    return BENCH_FULL


def keeps_cover(squad: Sequence[Candidate], sold: Candidate, bench: int = BENCH_FULL) -> bool:
    """After the sale the bench is still as the mode wants it (full: every position has a fit player
    beyond the ones the best eleven fields). An unfit player covers nothing, so selling one never breaks
    the cover."""
    if not sold.fit:
        return True
    rest = [p for p in squad if p.player_id != sold.player_id]
    return sold.position not in missing_cover(rest, bench)


def missing_cover(squad: Sequence[Candidate], bench: int = BENCH_FULL) -> list[int]:
    """Positions without the fit substitute the bench mode wants. MINIMAL names all field positions when
    no fit field player is left beyond the eleven: any of them covers."""
    if bench == BENCH_NONE:
        return []
    rows = coach.row_sizes(best_of(squad).formation)
    fit = {pos: sum(1 for p in squad if p.fit and p.position == pos) for pos in (1, 2, 3, 4)}
    if bench == BENCH_MINIMAL:
        field_spare = sum(fit[pos] - rows[pos] for pos in (2, 3, 4))
        return ([1] if fit[1] < rows[1] + 1 else []) + ([2, 3, 4] if field_spare < 1 else [])
    return [pos for pos in (1, 2, 3, 4) if fit[pos] < rows[pos] + 1]


def sell_order(squad: Iterable[Candidate], min_play: float) -> list[Candidate]:
    """Unavailable first, then the ones who rarely start, then the bench by the weakest daily rise."""
    return sorted(squad, key=lambda p: (p.fit, p.regular(min_play), p.in_best, p.today + p.forecast, p.expected))


def pick_sale(squad: Sequence[Candidate], target: Candidate, min_play: float, swap_edge: int,
              bench: int = BENCH_FULL) -> Candidate | None:
    """The one player to sell for `target`, an auction that may still be lost.

    `squad` is the confirmed squad only: the target is no cover and no starter yet. So the sale must
    leave the team as good as it is without him: never a fit player of the best eleven (also not the
    one the target would push out), never the last fit cover of a position, never a new gap in the
    eleven. Only a player who is unfit, no regular, or clearly rises less than the target (`swap_edge`
    per day, learned) is given up.
    """
    gaps = best_of(squad).empty_slots if squad else 0
    options = [
        p for p in squad
        if not p.locked and p.player_id != target.player_id and keeps_cover(squad, p, bench)
        and best_of([o for o in squad if o is not p]).empty_slots <= gaps
    ]
    for p in sell_order(options, min_play):
        if p.fit and p.in_best:
            continue
        if not p.fit or not p.regular(min_play):
            return p
        if target.forecast >= p.forecast + swap_edge and target.today >= p.today:
            return p
    return None


def starters_locked(fixtures: Iterable[coach.FixtureInfo], now: datetime, lock_minutes: int) -> bool:
    """From `lock_minutes` before a matchday's first kick-off until 5 minutes after it the starters stay:
    before, a sale leaves a gap in the eleven; after, Kickbase keeps their points."""
    days: dict[int, list[datetime]] = defaultdict(list)
    for f in fixtures:
        if f.kickoff is not None:
            days[f.day].append(f.kickoff)
    for kickoffs in days.values():
        first = min(kickoffs)
        if first - timedelta(minutes=lock_minutes) <= now < first + KICKOFF_GRACE:
            return True
    return False


### ===============================================================================
### Targets
### ===============================================================================


@dataclass(frozen=True)
class Upgrade:
    gain: float # Expected points the best eleven gains
    replaced: str | None # The player of the same position he pushes out of it
    replaced_value: int = 0
    fills: bool = False # He takes an empty slot of the eleven


### Season average and form weigh this much in the quality score (form reacts faster, the average is
### the larger sample). Not yet calibrated by a backtest (milestone 4)
AVERAGE_WEIGHT = 0.6
### Fewer matches than this of the last five: the data is thin, a swap needs this much more gain
THIN_SAMPLES = 3
THIN_FACTOR = 1.5


def quality(p: Candidate) -> float | None:
    """Average and form in one number, so a clearly better average can outweigh a slightly weaker
    recent form and the other way round. None when neither is known."""
    if p.average is not None and p.form is not None:
        return AVERAGE_WEIGHT * p.average + (1 - AVERAGE_WEIGHT) * p.form
    return p.average if p.average is not None else p.form


def lineup_upgrade(squad: Sequence[Candidate], target: Candidate, opts: Options) -> Upgrade | None:
    return upgrade_check(squad, target, opts)[0]


def upgrade_check(squad: Sequence[Candidate], target: Candidate, opts: Options) -> tuple[Upgrade | None, str | None]:
    """The upgrade, or None and the reason code (core.reasons) why `target` is none. `target` makes the eleven clearly better. Always: fit and a proven regular (`min_play`, known).

    An empty slot needs no more: a complete eleven beats a small gain (its price is judged by the
    real points). A swap also needs:
    - at least `min_gain` expected points more next matchday, half as much again when the target's
      data is thin (fewer than three of the last five matches),
    - a higher quality score (average and form weighed) by `min_avg_edge` percent; a target without
      any average or form is no swap, missing data is no proof,
    - not worse over the next three matches (`ahead`), so one easy opponent is no reason to buy.
    """
    if not target.fit:
        return None, "NOT_FIT"
    if target.play is None:
        return None, "PLAY_RATE_UNKNOWN"
    if target.play < opts.min_play / 100:
        return None, "PLAY_RATE_LOW"
    before = best_of(squad)
    after = best_of([*squad, target])
    if target.player_id not in after.player_ids:
        return None, "NO_ELEVEN_GAIN"
    fills = after.empty_slots < before.empty_slots
    ### The real points, not the empty slot penalty: price per point stays meaningful for a gap too
    gain = after.expected - before.expected
    thin = target.samples is not None and target.samples < THIN_SAMPLES
    if not fills and gain < max(opts.min_gain, 0.1) * (THIN_FACTOR if thin else 1.0):
        return None, "GAIN_BELOW_MIN"
    by_id = {p.player_id: p for p in squad}
    out = [by_id[pid] for pid in before.player_ids if pid not in after.player_ids and pid in by_id]
    same = [p for p in out if p.position == target.position]
    replaced = min(same or out, key=lambda p: p.expected) if out else None
    if replaced is not None and not fills:
        mine, theirs = quality(target), quality(replaced)
        if mine is None:
            return None, "QUALITY_UNKNOWN"
        ### A new formation: the season quality of a player of another position is no fair comparison,
        ### the points decide (the gain above and the next three matches below)
        cross = opts.upgrade_cross_position and replaced.position != target.position
        if not cross and theirs is not None and (mine <= theirs or mine < theirs * (1 + opts.min_avg_edge / 100)):
            return None, "QUALITY_EDGE"
        if target.ahead is not None and replaced.ahead is not None and target.ahead < replaced.ahead:
            return None, "LOOKAHEAD_WORSE"
    return Upgrade(round(gain, 1), replaced.player_id if replaced else None, replaced.value if replaced else 0, fills), None


def cost_per_point(upgrade: Upgrade, bid: int, ratio: float = 1.0) -> float:
    """The transfer difference per expected point: the bid minus what the replaced player would bring
    at the (conservative) instant sale ratio. He is not sold by this; it is the fair price comparison.
    The capital really tied up is the whole bid (see the debug log)."""
    return max(bid - upgrade.replaced_value * ratio, 0) / max(upgrade.gain, 0.1)


def worth_it(upgrade: Upgrade, bid: int, opts: Options, ratio: float = 1.0) -> bool:
    return cost_per_point(upgrade, bid, ratio) <= opts.max_cost_per_point


def cover_target(squad: Sequence[Candidate], market: Iterable[Candidate], opts: Options,
                 bench: int = BENCH_FULL) -> Candidate | None:
    """The cheapest fit player of a position without a substitute who plays at least now and then
    and is not falling."""
    missing = set(missing_cover(squad, bench))
    if not missing:
        return None
    options = [
        c
        for c in market
        if c.position in missing
        and c.fit
        and c.play is not None
        and c.play >= opts.min_play / 200
        and c.forecast >= 0
        and max(c.bid_low, c.price, c.value) <= opts.cover_max_price
    ]
    return min(options, key=lambda c: (max(c.bid_low, c.price, c.value), -c.expected), default=None)


def liquidation_value(squad: Sequence[Candidate], ratio: float, max_sales: int, bench: int = BENCH_FULL) -> int:
    """What selling players really brings in before a deadline, sold one after the other in the sell
    order: never a locked player, never one of the best eleven, never the last fit cover of a position,
    at most `max_sales` sales, each valued at its value after a forecast fall times the sell ratio.
    Only the confirmed squad counts, open bids are no collateral."""
    remaining = list(squad)
    total = sales = 0
    for p in sell_order(squad, 1.0):
        if sales >= max_sales:
            break
        if p.locked or p.in_best or not keeps_cover(remaining, p, bench):
            continue
        total += int(max(p.value + min(p.forecast, 0), 0) * ratio)
        remaining.remove(p)
        sales += 1
    return total


def credit(budget: int, team_value: int, repayable: int) -> int:
    """The money the trader may spend beyond the balance: up to the max bid of the 33 % rule, but
    never more debt than the simulated liquidation (`liquidation_value`) pays back before the deadline."""
    room = analytics.max_bid(budget, team_value) - max(budget, 0)
    return max(0, min(room, repayable - max(0, -budget)))


### Why the money the trader releases is below the max bid Kickbase allows. Stable codes, for logs and the UI
LIMIT_RESERVE = "RESERVE" # Never spent (option `reserve`)
LIMIT_DEBT = "DEBT" # A negative balance already uses up part of the max bid
LIMIT_LIQUIDATION = "LIQUIDATION" # Credit only as far as selling sellable players pays it back
LIMIT_CREDIT_MODE = "CREDIT_MODE" # The credit mode gives this purpose no credit
LIMIT_PHASE = "PHASE" # Close to the deadline this purpose gets no credit
LIMIT_PROFIT_ROOM = "PROFIT_ROOM" # Profit positions together stay within `profit_share`


def money_check(budget: int, team_value: int, open_bids: int, reserve: int, loan: int, credits: dict[str, int],
                credit_anyway: dict[str, int], profit_room: int) -> dict:
    """The max bid next to the money released per purpose, and what makes up the difference.

    `credits` is the credit each purpose may use in this phase and mode, `credit_anyway` the same in the
    normal phase (tells the credit mode from the phase). The limits add up to the difference exactly:
    max bid after open bids − released = reserve + debt + (credit room − loan) + (loan − credit) [+ profit room].
    Bids may still keep money back for empty slots and missing substitutes, that is per bid and not in here.
    """
    max_bid = analytics.max_bid(budget, team_value)
    room = max_bid - max(budget, 0)
    free_max = max_bid - open_bids
    released: dict[str, int] = {}
    limits: dict[str, dict[str, int]] = {}
    for purpose, credit_now in credits.items():
        raw = budget - reserve - open_bids + credit_now
        parts = {LIMIT_RESERVE: reserve, LIMIT_DEBT: max(0, -budget), LIMIT_LIQUIDATION: room - loan}
        parts[LIMIT_PHASE if credit_anyway.get(purpose, 0) > credit_now else LIMIT_CREDIT_MODE] = loan - credit_now
        value = raw
        if purpose == "profit" and raw > profit_room:
            value = profit_room
            parts[LIMIT_PROFIT_ROOM] = raw - profit_room
        released[purpose] = value
        limits[purpose] = {code: amount for code, amount in parts.items() if amount}
    return {"max_bid": max_bid, "open_bids": open_bids, "max_bid_free": free_max, "released": released,
            "gap": {p: free_max - v for p, v in released.items()}, "limits": limits}


def repay_from(deadline: datetime) -> datetime:
    """When debt is paid back before a matchday: right after the last market value update before
    the deadline, as sales fetch the same from then on. At least an hour before the deadline."""
    update = analytics.last_market_value_update(deadline) + timedelta(minutes=15)
    return min(update, deadline - timedelta(hours=1))


### Deadline phases. Stateless: rebuilt from the clock and the deadline every round, also after a restart
PREPARE_BEFORE = timedelta(hours=24)
FINAL_BEFORE = timedelta(minutes=60)


def phase(now: datetime, deadline: datetime | None) -> str:
    """normal; prepare (24 h before: no credit for profit trades); repay (from the last market value
    update: debt is paid back, no credit for auctions ending before the deadline, profit bids only on
    auctions ending after it); final (last hour: no new profit bids, no credit)."""
    if deadline is None or now >= deadline:
        return "normal"
    if deadline - now <= FINAL_BEFORE:
        return "final"
    if now >= repay_from(deadline):
        return "repay"
    if deadline - now <= PREPARE_BEFORE:
        return "prepare"
    return "normal"


### ===============================================================================
### Net profit: what a profit buy brings after selling it again
### ===============================================================================


def expected_proceeds(target: Candidate, ratio: float) -> int:
    """The value after the holding time, sold at the (conservative) instant sale ratio."""
    return int(max(target.value + target.gain, 0) * ratio)


def expected_profit(target: Candidate, bid: int, ratio: float) -> int:
    """Net: proceeds of the sale minus the bid. Kickbase charges no fee, the sale ratio is the cost."""
    return expected_proceeds(target, ratio) - bid


def max_profit_bid(target: Candidate, ratio: float, min_margin: int, min_roi: float) -> int:
    """The most a profit buy may cost: it still keeps `min_margin` euro and `min_roi` (share) net."""
    proceeds = expected_proceeds(target, ratio)
    limit = min(proceeds - min_margin, proceeds / (1 + max(min_roi, 0.0)))
    return int(limit // coach.BID_STEP * coach.BID_STEP)


def is_profit_buy(target: Candidate, bid: int, min_margin: int, ratio: float, min_roi: float) -> bool:
    if bid <= 0 or not target.fit or target.forecast <= 0 or target.today < 0:
        return False
    profit = expected_profit(target, bid, ratio)
    return profit >= min_margin and profit >= bid * min_roi


def profit_rank(target: Candidate, bid: int, ratio: float) -> float:
    """Net return per euro and market value update: a cheap player with a good return beats an
    expensive one that only makes more in absolute terms."""
    return expected_profit(target, bid, ratio) / max(bid, 1) / PROFIT_HOLD


### ===============================================================================
### Priorities: what goes first depends on how close the matchday is
### ===============================================================================

### Tier per purpose. Normal trading: fill the eleven, improve it, profit, substitutes. Close to a
### matchday (prepare/repay/final): fill the eleven, substitutes, improve it, profit last
TIERS = {
    False: {"fill": 4, "lineup": 3, "profit": 2, "cover": 1},
    True: {"fill": 4, "cover": 3, "lineup": 2, "profit": 0},
}


def priority(purpose: str, fills: bool, stage: str, score: float) -> tuple[int, float]:
    """Sort key, highest first: the tier of the purpose in this phase, then its own score (points
    gained, net return per euro, or the lower price of a substitute)."""
    near = stage in ("prepare", "repay", "final")
    return TIERS[near]["fill" if fills else purpose], score


### ===============================================================================
### Selling profit positions: compare holding with selling
### ===============================================================================

### A forecast fall of this share of the value (or a fall today too) is a real turn, not noise
TURN_SHARE = 0.005


def exit_reason(p: Candidate, cost: int, peak: int | None, held_days: int, ratio: float, min_margin: int,
                opts: Options) -> tuple[str, str] | None:
    """Why a profit position should be sold now, or None to keep holding. Selling brings
    `value x ratio` now; holding brings the forecast gain (`gain x ratio`) later, with its risk.

    In this order: sporting failure; position stop-loss; trailing stop; forecast turn (confirmed by a
    fall today or a clear forecast fall); take profit (in profit and holding brings less than the
    minimum margin); time limit (held too long without enough left to gain). Stops and trails only
    fire while the forecast is not rising again, so a dip the forecast sees recovering is held.
    """
    proceeds = int(p.value * ratio)
    pnl = proceeds - cost
    further = int(max(p.gain, 0) * ratio)
    if not p.fit:
        return "SPORT", "verletzt oder fällt aus"
    if opts.position_stop and pnl <= -cost * opts.position_stop / 100 and p.forecast <= 0:
        return "STOP", f"Verlust {pnl / 1e3:+.0f} Tsd. € erreicht die Positionsgrenze"
    if opts.trailing_stop and peak is not None and int(peak * ratio) > cost and p.value <= peak * (1 - opts.trailing_stop / 100) and p.forecast <= 0:
        return "TRAIL", f"{(peak - p.value) / 1e3:.0f} Tsd. € unter dem Höchststand seit dem Kauf"
    if p.forecast < 0 and (p.today < 0 or p.forecast <= -p.value * TURN_SHARE):
        return "TURN", "Prognose dreht ins Minus"
    if pnl > 0 and further < min_margin:
        return "TAKE", f"Gewinn {pnl / 1e3:+.0f} Tsd. € gesichert, Halten bringt kaum mehr"
    if opts.max_hold_days and held_days >= opts.max_hold_days and further < min_margin:
        return "TIME", f"seit {held_days} Tagen gehalten ohne genug Aussicht"
    return None


### ===============================================================================
### The price
### ===============================================================================


def bid_for(target: Candidate, extra: float, cap: int | None) -> int | None:
    """Between the league's usual markup (`bid_low`) and enough to beat the likely bidders
    (`bid_high`); `extra` (0..1) is learned from won and lost auctions per price class.

    Rounded up to the bid step and checked after rounding: never below the minimum, never above
    `cap` (the smallest of every limit). No bid without a valid price."""
    low = max(target.bid_low, target.price, target.value)
    if low <= 0:
        return None
    high = max(target.bid_high, low)
    bid = low + min(max(extra, 0.0), 1.0) * (high - low)
    bid = math.ceil(bid / coach.BID_STEP) * coach.BID_STEP
    if cap is not None and bid > cap:
        bid = cap // coach.BID_STEP * coach.BID_STEP # The most the cap allows, if still a valid bid
    if bid < low:
        return None
    return int(bid)


### ===============================================================================
### Bids by expected value: P(win) from the league's auctions times what winning is worth
### ===============================================================================

### Fewer won auctions than this in the league (and price class): no model, the learned extra decides
MIN_AUCTIONS = 8
### Bids tried between the minimum and the cap
BID_GRID = 40


def winning_markups(shares: Sequence[tuple[int, float]], value: int) -> list[float]:
    """The markups that won comparable auctions: the player's price class when it has enough, else
    the whole league."""
    same = [s for v, s in shares if coach.price_class(v) == coach.price_class(value)]
    return same if len(same) >= MIN_AUCTIONS else [s for _, s in shares]


def win_probability(bid: int, value: int, markups: Sequence[float]) -> float | None:
    """Share of the league's won auctions a bid would have beaten: the winner paid less on top of the
    market value. A tie counts as lost (unknown who gets it). None without enough auctions.
    Auctions nobody bid on never show up, so this errs on the low side."""
    if len(markups) < MIN_AUCTIONS or value <= 0:
        return None
    share = (bid - value) / value
    return sum(1 for m in markups if m < share - 1e-9) / len(markups) # Float noise must not turn a tie into a win


def best_bid(target: Candidate, worth: int, cap: int, markups: Sequence[float]) -> tuple[int, float, int] | None:
    """The bid with the highest expected value `P(win) x (worth - bid)` between the minimum bid and
    `cap`, as (bid, P(win), expected value). `worth` is what winning is worth: the net sale proceeds
    of a profit buy, the points gained times the price per point for the eleven. None when no bid has
    a positive expected value or the league has too few auctions."""
    low = max(target.price, target.value)
    high = min(cap, worth)
    if low <= 0 or high < low or len(markups) < MIN_AUCTIONS:
        return None
    step = max(coach.BID_STEP, (high - low) // BID_GRID // coach.BID_STEP * coach.BID_STEP)
    best: tuple[int, float, int] | None = None
    bid = math.ceil(low / coach.BID_STEP) * coach.BID_STEP
    while bid <= high:
        p = win_probability(bid, target.value, markups) or 0.0
        ev = int(p * (worth - bid))
        if ev > 0 and (best is None or ev > best[2]):
            best = (bid, p, ev)
        bid += step
    return best


### ===============================================================================
### Learning: a global base model, the bidding per league on top
### ===============================================================================

### Version of the stored learning state; older states are read as they are (missing keys: defaults)
MODEL_VERSION = 2
### Auctions of a league after which its own bid heights count as much as the global ones
LEAGUE_PRIOR = 10

START_EXTRA = 0.3
START_MARGIN = 150_000
START_SWAP_EDGE = 100_000
### A learned correction is only used after this many observations
MIN_SAMPLES = 10
### Shadow trades count half as much as real ones
SHADOW_WEIGHT = 0.5


@dataclass(frozen=True)
class Learned:
    extra: tuple[float, ...] = (START_EXTRA,) * len(coach.PRICE_CLASSES)
    min_margin: int = START_MARGIN
    won: int = 0
    lost: int = 0
    ### What a forecast gain turned out to be worth (actual / forecast), smoothed
    gain_ratio: float = 1.0
    gain_samples: int = 0
    ### How much more per day a swap target has to rise than the player sold for him
    swap_edge: int = START_SWAP_EDGE
    regret_samples: int = 0
    shadow_won: int = 0
    shadow_lost: int = 0
    ### Forecasts whose direction came true (a gain was forecast, a gain came), of gain_samples
    direction_hits: int = 0
    ### 1 while the forecast is systematically wrong: no profit buys, paper trades keep learning
    forecast_pause: int = 0

    @property
    def gain_scale(self) -> float:
        """The forecast gain is trusted this much: conservative, a forecast that came true more than
        promised is not trusted beyond 1.0. 1.0 until there are enough observations."""
        return min(1.0, max(0.3, self.gain_ratio)) if self.gain_samples >= MIN_SAMPLES else 1.0

    @classmethod
    def load(cls, data: dict | None) -> Learned:
        """Junk, NaN and infinity are dropped and every value clamped: it is also what an import sends."""
        data = data if isinstance(data, dict) else {}
        extra: tuple[float, ...] = cls.extra
        with contextlib.suppress(TypeError, ValueError):
            given = tuple(parse_number(x) for x in data.get("extra", ()))
            if len(given) == len(coach.PRICE_CLASSES) and all(x is not None for x in given):
                extra = tuple(min(1.0, max(0.0, x)) for x in given) # type: ignore[type-var]
        known = {f.name for f in fields(cls)} - {"extra"}
        values = {}
        for f in fields(cls):
            if f.name in known and f.name in data:
                number = parse_number(data[f.name])
                if number is None:
                    continue
                low, high = LEARNED_LIMITS.get(f.name, (0, 10**9))
                values[f.name] = type(getattr(cls, f.name))(min(max(number, low), high))
        return cls(extra=extra, **values)

    def dump(self) -> dict:
        return {"version": MODEL_VERSION} | {f.name: list(self.extra) if f.name == "extra" else getattr(self, f.name) for f in fields(self)}

    @property
    def direction_rate(self) -> float | None:
        """How often the forecast got the direction right, once there are enough forecasts."""
        return self.direction_hits / self.gain_samples if self.gain_samples >= MIN_SAMPLES else None


def blend(base: Learned, league: Learned) -> Learned:
    """The model one league trades with: the global base for the forecast, the margin and the swap
    edge; the bid heights mixed with the league's own, more of them the more auctions it had. A new
    league starts with the global experience."""
    n = league.won + league.lost + SHADOW_WEIGHT * (league.shadow_won + league.shadow_lost)
    w = n / (n + LEAGUE_PRIOR)
    extra = tuple(round(w * mine + (1 - w) * theirs, 3) for mine, theirs in zip(league.extra, base.extra, strict=True))
    return replace(base, extra=extra, won=league.won, lost=league.lost, shadow_won=league.shadow_won, shadow_lost=league.shadow_lost)


### The ranges the learning keeps itself in, the same for an import. Counters only need to be >= 0
LEARNED_LIMITS: dict[str, tuple[float, float]] = {
    "extra": (0.0, 1.0),
    "min_margin": (50_000, 1_500_000),
    "gain_ratio": (-1.0, 2.0),
    "swap_edge": (50_000, 1_000_000),
    "forecast_pause": (0, 1),
}


def constants() -> dict[str, object]:
    """The fixed rules, exported so an outside review knows them. Changing one needs a new build."""
    return {
        "PROFIT_HOLD_UPDATES": PROFIT_HOLD, "REGRET_DAYS": REGRET_DAYS, "REBUY_BLOCK_DAYS": REBUY_BLOCK.days,
        "MIN_HOLD_HOURS": MIN_HOLD.total_seconds() / 3600, "KICKOFF_GRACE_MINUTES": KICKOFF_GRACE.total_seconds() / 60,
        "ROOM_EXTRA": ROOM_EXTRA, "MIN_SAMPLES": MIN_SAMPLES, "SHADOW_WEIGHT": SHADOW_WEIGHT,
        "EMPTY_SLOT_PENALTY": coach.EMPTY_SLOT, "PRICE_CLASSES": list(coach.PRICE_CLASSES), "BID_STEP": coach.BID_STEP,
        "MIN_AUCTIONS": MIN_AUCTIONS, "LEAGUE_PRIOR": LEAGUE_PRIOR, "PAUSE_BELOW": PAUSE_BELOW, "RESUME_ABOVE": RESUME_ABOVE,
        "MODEL_VERSION": MODEL_VERSION,
    }


def after_auction(state: Learned, value: int, won: bool, own: int, winner: int | None, weight: float = 1.0) -> Learned:
    """Won: try a little cheaper next time. Lost to a higher bid: bid clearly more in that price class."""
    index = coach.price_class(value)
    extra = list(state.extra)
    shadow = weight < 1
    if won:
        extra[index] = max(0.0, extra[index] - 0.05 * weight)
        counts = {"shadow_won": state.shadow_won + 1} if shadow else {"won": state.won + 1}
        return replace(state, extra=tuple(round(x, 3) for x in extra), **counts)
    if winner is not None and winner > own:
        extra[index] = min(1.0, extra[index] + 0.15 * weight)
    counts = {"shadow_lost": state.shadow_lost + 1} if shadow else {"lost": state.lost + 1}
    return replace(state, extra=tuple(round(x, 3) for x in extra), **counts)


def after_sale(state: Learned, profit: int, weight: float = 1.0) -> Learned:
    """A net loss makes the trader pickier, the more the bigger it was (5 to 20 %); a net gain
    a little less so (1 to 3 %): a small gain does not make up for a big loss."""
    size = min(abs(profit) / max(state.min_margin, 1), 3.0)
    factor = 1 + 0.05 * weight * (1 + size) if profit < 0 else 1 - 0.01 * weight * (1 + min(size, 2.0))
    return replace(state, min_margin=int(min(1_500_000, max(50_000, state.min_margin * factor))))


### Forecasts that bring less than this share of what they promised pause the profit trading; it
### resumes above the second value (hysteresis, so it does not flip every update)
PAUSE_BELOW, RESUME_ABOVE = 0.3, 0.45


def after_forecast(state: Learned, forecast_gain: int, actual_gain: int, weight: float = 1.0) -> Learned:
    """Smooths how much of a forecast gain really came, over the same horizon it was made for
    (PROFIT_HOLD updates), counts whether the direction was right, and pauses the profit trading
    while the forecast is systematically wrong. Tiny forecasts say nothing and are skipped; paper
    trades weigh `weight`."""
    if forecast_gain < 50_000:
        return state
    ratio = min(2.0, max(-1.0, actual_gain / forecast_gain))
    alpha = 0.1 * min(max(weight, 0.0), 1.0)
    gain_ratio = round((1 - alpha) * state.gain_ratio + alpha * ratio, 4)
    samples = state.gain_samples + 1
    pause = state.forecast_pause
    if samples >= MIN_SAMPLES:
        pause = 1 if gain_ratio < PAUSE_BELOW else 0 if gain_ratio > RESUME_ABOVE else pause
    return replace(state, gain_ratio=gain_ratio, gain_samples=samples, forecast_pause=pause,
                   direction_hits=state.direction_hits + (1 if actual_gain > 0 else 0))


def after_regret(state: Learned, change_after_sale: int) -> Learned:
    """A sold player who rose clearly afterwards (net of the sale ratio, against simply holding him):
    swaps need a bigger edge. Otherwise a little smaller. Rescue sales are not judged by this."""
    factor = 1.1 if change_after_sale > 100_000 else 0.97
    edge = int(min(1_000_000, max(50_000, state.swap_edge * factor)))
    return replace(state, swap_edge=edge, regret_samples=state.regret_samples + 1)


### ===============================================================================
### Weekly statistics
### ===============================================================================


@dataclass(frozen=True)
class Trade:
    at: datetime
    kind: str # bid, sell or shadow
    status: str # planned, open, won, lost, expired, sold; shadow: done
    price: int
    paid: int | None = None
    profit: int | None = None
    points_gain: float = 0


### A Kickbase call that was sent but not (yet) confirmed: checked against Kickbase in the next round
UNSETTLED = ("pending", "unknown")


def week_of(at: datetime) -> str:
    """ISO week in German time, so a Sunday evening sale is not filed under the next week."""
    year, week, _ = at.astimezone(analytics.MARKET_VALUE_TIMEZONE).isocalendar()
    return f"{year}-W{week:02d}"


def weekly(trades: Iterable[Trade]) -> list[dict]:
    """Per ISO week, newest first: bids, won and lost auctions, money spent and received, realized
    profit, the expected points the lineup purchases added, and what the paper trades made."""
    weeks: dict[str, dict] = defaultdict(
        lambda: {
            "planned": 0, "bids": 0, "won": 0, "lost": 0, "sales": 0, "spent": 0, "received": 0, "profit": 0,
            "points_gain": 0.0, "shadow_trades": 0, "shadow_profit": 0, "unknown": 0,
        }
    )
    for t in trades:
        w = weeks[week_of(t.at)]
        if t.kind == "shadow":
            if t.status == "done":
                w["shadow_trades"] += 1
                w["shadow_profit"] += t.profit or 0
        elif t.status == "planned":
            w["planned"] += 1
        elif t.status in UNSETTLED or t.status == "failed":
            continue # Not a trade (yet): never counted, never 0 € profit
        elif t.kind == "bid":
            w["bids"] += 1
            if t.status == "won":
                w["won"] += 1
                w["spent"] += t.paid or t.price
                w["points_gain"] = round(w["points_gain"] + t.points_gain, 1)
            elif t.status == "lost":
                w["lost"] += 1
        elif t.kind == "sell" and t.status == "sold":
            w["sales"] += 1
            w["received"] += t.price
            if t.profit is None:
                w["unknown"] += 1 # Proceeds or price unknown: counted apart, never as 0 €
            else:
                w["profit"] += t.profit
    return [{"week": key, **weeks[key]} for key in sorted(weeks, reverse=True)]
