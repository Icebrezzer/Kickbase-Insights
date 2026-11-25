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

from core import coach

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
    daily_bids: int = 6
    daily_sales: int = 3
    stop_loss: int = 3_000_000 # Realized weekly loss that pauses the profit trading
    sell_window: int = 20 # Minutes before an auction ends when a player is sold to make room
    starter_lock: int = 60 # Minutes before the first kick-off from which starters are kept
    shadow: bool = True # Learn from paper trades too

    @classmethod
    def load(cls, data: dict | None) -> Options:
        """Unknown keys are dropped, every value is clamped: the stored JSON is not trusted."""
        data = data or {}
        values = {}
        for f in fields(cls):
            if f.name not in data or data[f.name] is None:
                continue
            raw = data[f.name]
            if f.name == "shadow":
                values[f.name] = bool(raw)
                continue
            try:
                number = float(raw)
            except (TypeError, ValueError):
                continue
            low, high = OPTION_LIMITS[f.name]
            number = min(max(number, low), high)
            values[f.name] = number if f.name == "min_gain" else int(number)
        return cls(**values)


OPTION_LIMITS: dict[str, tuple[float, float]] = {
    "min_gain": (0.0, 100.0),
    "max_cost_per_point": (0, 50_000_000),
    "min_avg_edge": (0, 200),
    "min_play": (0, 100),
    "lineup_share": (10, 100),
    "profit_share": (10, 100),
    "reserve": (0, 500_000_000),
    "cover_max_price": (0, 50_000_000),
    "daily_bids": (0, 30),
    "daily_sales": (0, 30),
    "stop_loss": (0, 100_000_000),
    "sell_window": (5, 180),
    "starter_lock": (0, 24 * 60),
}


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


def keeps_cover(squad: Sequence[Candidate], sold: Candidate) -> bool:
    """After the sale every position still has a fit player beyond the ones the best eleven fields.

    An unfit player covers nothing, so selling one never breaks the cover."""
    if not sold.fit:
        return True
    rest = [p for p in squad if p.player_id != sold.player_id]
    rows = coach.row_sizes(best_of(rest).formation)
    fit_here = sum(1 for p in rest if p.fit and p.position == sold.position)
    return fit_here >= rows[sold.position] + 1


def missing_cover(squad: Sequence[Candidate]) -> list[int]:
    """Positions without a fit substitute beyond the best eleven."""
    rows = coach.row_sizes(best_of(squad).formation)
    return [pos for pos in (1, 2, 3, 4) if sum(1 for p in squad if p.fit and p.position == pos) < rows[pos] + 1]


def sell_order(squad: Iterable[Candidate], min_play: float) -> list[Candidate]:
    """Unavailable first, then the ones who rarely start, then the bench by the weakest daily rise."""
    return sorted(squad, key=lambda p: (p.fit, p.regular(min_play), p.in_best, p.today + p.forecast, p.expected))


def pick_sale(
    squad: Sequence[Candidate], target: Candidate, min_play: float, swap_edge: int, replaced: str | None = None
) -> Candidate | None:
    """The one player to sell for `target`.

    For a lineup purchase the player he pushes out goes first. Otherwise only a player who is unfit,
    no regular, or clearly rises less than the target (`swap_edge` per day, learned) is given up,
    never one of the best eleven while he is fit.
    """
    options = [p for p in squad if not p.locked and p.player_id != target.player_id and keeps_cover(squad, p)]
    if replaced:
        pushed = next((p for p in options if p.player_id == replaced), None)
        if pushed is not None:
            return pushed
    for p in sell_order(options, min_play):
        if not p.fit or not p.regular(min_play):
            return p
        if p.in_best:
            continue
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


def lineup_upgrade(squad: Sequence[Candidate], target: Candidate, opts: Options) -> Upgrade | None:
    """`target` makes the eleven clearly better: at least `min_gain` expected points more, a proven
    regular, and a better season average (by `min_avg_edge`) and form than the player he replaces.
    An empty slot only needs him to be fit and a regular."""
    if not target.fit or target.play is None or target.play < opts.min_play / 100:
        return None
    before = best_of(squad)
    after = best_of([*squad, target])
    if target.player_id not in after.player_ids:
        return None
    gain = (after.expected - after.empty_slots * coach.EMPTY_SLOT) - (before.expected - before.empty_slots * coach.EMPTY_SLOT)
    if gain < max(opts.min_gain, 0.1):
        return None
    by_id = {p.player_id: p for p in squad}
    out = [by_id[pid] for pid in before.player_ids if pid not in after.player_ids and pid in by_id]
    same = [p for p in out if p.position == target.position]
    replaced = min(same or out, key=lambda p: p.expected) if out else None
    if replaced is not None:
        if (
            target.average is not None
            and replaced.average is not None
            and (target.average < replaced.average * (1 + opts.min_avg_edge / 100) or target.average <= replaced.average)
        ):
            return None
        if target.form is not None and replaced.form is not None and target.form <= replaced.form:
            return None
    return Upgrade(round(gain, 1), replaced.player_id if replaced else None, replaced.value if replaced else 0)


def cost_per_point(upgrade: Upgrade, bid: int) -> float:
    """What the bid costs above the replaced player's value, per expected point gained."""
    return max(bid - upgrade.replaced_value, 0) / max(upgrade.gain, 0.1)


def worth_it(upgrade: Upgrade, bid: int, opts: Options) -> bool:
    return cost_per_point(upgrade, bid) <= opts.max_cost_per_point


def cover_target(squad: Sequence[Candidate], market: Iterable[Candidate], opts: Options) -> Candidate | None:
    """The cheapest fit player of a position without a substitute who plays at least now and then
    and is not falling."""
    missing = set(missing_cover(squad))
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


def profit_margin(target: Candidate, bid: int) -> int:
    """Forecast gain over the holding time minus what the bid is above the market value."""
    return target.gain - max(bid - target.value, 0)


def is_profit_buy(target: Candidate, bid: int, min_margin: int) -> bool:
    return target.fit and target.forecast > 0 and target.today >= 0 and profit_margin(target, bid) >= min_margin


### ===============================================================================
### The price
### ===============================================================================


def bid_for(target: Candidate, extra: float, cap: int | None, profit: bool) -> int | None:
    """Between the league's usual markup (`bid_low`) and enough to beat the likely bidders
    (`bid_high`); `extra` (0..1) is learned from won and lost auctions per price class.

    A profit buy keeps at least half of the forecast gain, and no bid goes beyond `cap`."""
    low = max(target.bid_low, target.price, target.value)
    high = max(target.bid_high, low)
    bid = low + min(max(extra, 0.0), 1.0) * (high - low)
    if profit:
        bid = min(bid, target.value + max(target.gain, 0) / 2)
    bid = math.ceil(bid / coach.BID_STEP) * coach.BID_STEP
    if bid < low:
        return None
    if cap is not None and bid > cap:
        return None
    return int(bid)


### ===============================================================================
### Learning, shared by all leagues
### ===============================================================================

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

    @property
    def gain_scale(self) -> float:
        """The forecast gain is trusted this much. 1.0 until there are enough observations."""
        return min(1.2, max(0.3, self.gain_ratio)) if self.gain_samples >= MIN_SAMPLES else 1.0

    @classmethod
    def load(cls, data: dict) -> Learned:
        extra = tuple(float(x) for x in data.get("extra", ()))
        if len(extra) != len(coach.PRICE_CLASSES):
            extra = cls.extra
        known = {f.name for f in fields(cls)} - {"extra"}
        values = {}
        for f in fields(cls):
            if f.name in known and f.name in data:
                with contextlib.suppress(TypeError, ValueError):
                    values[f.name] = type(getattr(cls, f.name))(data[f.name])
        return cls(extra=extra, **values)

    def dump(self) -> dict:
        return {f.name: list(self.extra) if f.name == "extra" else getattr(self, f.name) for f in fields(self)}


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
    """A losing profit trade makes the trader pickier, a winning one a little less so."""
    factor = 1 + (0.15 if profit < 0 else -0.03) * weight
    return replace(state, min_margin=int(min(1_500_000, max(50_000, state.min_margin * factor))))


def after_forecast(state: Learned, forecast_gain: int, actual_gain: int) -> Learned:
    """Smooths how much of a forecast gain really came. Tiny forecasts say nothing and are skipped."""
    if forecast_gain < 50_000:
        return state
    ratio = min(2.0, max(-1.0, actual_gain / forecast_gain))
    return replace(state, gain_ratio=round(0.9 * state.gain_ratio + 0.1 * ratio, 4), gain_samples=state.gain_samples + 1)


def after_regret(state: Learned, change_after_sale: int) -> Learned:
    """A sold player who rose clearly afterwards: swaps need a bigger edge. Otherwise a little smaller."""
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


def week_of(at: datetime) -> str:
    year, week, _ = at.isocalendar()
    return f"{year}-W{week:02d}"


def weekly(trades: Iterable[Trade]) -> list[dict]:
    """Per ISO week, newest first: bids, won and lost auctions, money spent and received, realized
    profit, the expected points the lineup purchases added, and what the paper trades made."""
    weeks: dict[str, dict] = defaultdict(
        lambda: {
            "planned": 0, "bids": 0, "won": 0, "lost": 0, "sales": 0, "spent": 0, "received": 0, "profit": 0,
            "points_gain": 0.0, "shadow_trades": 0, "shadow_profit": 0,
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
            w["profit"] += t.profit or 0
    return [{"week": key, **weeks[key]} for key in sorted(weeks, reverse=True)]
