"""Backtest of the autotrader's profit trading on the league's real auctions.

What it replays: every purchase from Kickbase in the league is an auction that really took place, with
the price the winner really paid. On the auction's day a strategy decides with what it could have
known then - the market values up to that day, a forecast model fitted only on the days before the
test window (walk-forward), win probabilities only from earlier auctions - whether to bid and how
much. The bid wins only if it was above the real winner's price (a tie is lost). A won player is held
day by day with the same exit rules as live and sold at the day's value times the sell ratio.

What it cannot replay (no data, nothing made up): which other players were listed, the player's
fitness on that day, the starting eleven and its points, other managers' reactions to a different
winner, and matchday deadlines. So it compares profit trading strategies, not the whole trader.
Results are no promise of future profit.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace

from core import coach
from core import trader as t

### Positions the profit trading holds at most at once
MAX_POSITIONS = 5
### Days of market values a test window needs before it
MIN_TRAINING_DAYS = 21


@dataclass(frozen=True)
class Auction:
    day: int # Market value day of the purchase
    player_id: str
    price: int # What the winner paid
    value: int # Market value that day


@dataclass
class Result:
    strategy: str
    trades: int = 0
    won: int = 0
    lost: int = 0
    skipped: int = 0
    profit: int = 0 # Realized net, sales at value x ratio minus the price paid
    losing_trades: int = 0
    hold_days: int = 0
    invested_days: int = 0 # Sum over days of the capital in positions (for return per euro and day)
    max_drawdown: int = 0
    net: int = 0 # Sum over the windows of the cash at the end (all positions sold) minus the start
    equity: list[tuple[int, int]] = field(default_factory=list)
    exits: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    def summary(self, start: int) -> dict:
        return {
            "strategy": self.strategy,
            "net_profit": self.net,
            "realized": self.profit,
            "return_pct": round(self.net / start * 100, 2) if start else None,
            "max_drawdown": self.max_drawdown,
            "bids": self.won + self.lost,
            "won": self.won,
            "lost": self.lost,
            "trades": self.trades,
            "losing_trades": self.losing_trades,
            "avg_hold_days": round(self.hold_days / self.trades, 1) if self.trades else None,
            "return_per_euro_day": round(self.profit / self.invested_days, 6) if self.invested_days else None,
            "exits": dict(self.exits),
        }


def _value(points: Sequence[Sequence[int]], day: int) -> int | None:
    """The market value in force on `day`: the latest entry at or before it."""
    value = None
    for d, v in points:
        if d > day:
            break
        value = v
    return value


def _until(points: Sequence[Sequence[int]], day: int) -> list:
    return [p for p in points if p[0] <= day]


def _candidate(pid: str, points: Sequence[Sequence[int]], day: int, model: coach.ForecastModel,
               matches: Sequence | None, value: int) -> t.Candidate | None:
    """What the trader knew about a player on `day`: only the history up to it."""
    known = _until(points, day)
    prediction = coach.forecast(known, model, t.PROFIT_HOLD, [m for m in matches or [] if m[0] <= day])
    if prediction is None:
        return None
    today = known[-1][1] - known[-2][1] if len(known) >= 2 and known[-1][0] - known[-2][0] == 1 else 0
    ### Fitness on that day is not stored: taken as fit (stated as a limit)
    return t.Candidate(pid, 0, 0.0, None, None, None, True, today, prediction.next_change, prediction.projection[-1], value, price=value)


def _new_buy(c: t.Candidate, markups: Sequence[float], cash: int, room: int, opts: t.Options, ratio: float) -> int | None:
    """Today's rules: net profit after the sale ratio, minimum margin and return, bid by expected value."""
    margin = t.Learned().min_margin
    cap = min(cash, room, t.max_profit_bid(c, ratio, margin, opts.min_roi / 100))
    chosen = t.best_bid(c, t.expected_proceeds(c, ratio), cap, markups)
    if chosen is None:
        low = coach._quantile(markups, 0.5) if markups else 0.03
        high = coach._quantile(markups, 0.75) if markups else 0.08
        c = replace(c, bid_low=int(c.value * (1 + low)), bid_high=int(c.value * (1 + high)))
        bid = t.bid_for(c, t.START_EXTRA, cap)
    else:
        bid = chosen[0]
    return bid if bid is not None and t.is_profit_buy(c, bid, margin, ratio, opts.min_roi / 100) else None


def _reference_buy(c: t.Candidate, markups: Sequence[float], cash: int, room: int, opts: t.Options, ratio: float) -> int | None:
    """The strategy before the safety patch, kept to compare fairly: gross margin without the sale
    ratio (gain - markup >= 150k), the learned height between median and 75 % markup, at most value
    plus half the gain."""
    if not (c.fit and c.forecast > 0 and c.today >= 0):
        return None
    low = coach._quantile(markups, 0.5) if markups else 0.03
    high = coach._quantile(markups, 0.75) if markups else 0.08
    lo, hi = int(c.value * (1 + low)), int(c.value * (1 + high))
    bid = min(lo + t.START_EXTRA * (hi - lo), c.value + max(c.gain, 0) / 2)
    bid = int(-(-bid // coach.BID_STEP) * coach.BID_STEP)
    if bid < max(c.value, lo) or bid > min(cash, room):
        return None
    return bid if c.gain - max(bid - c.value, 0) >= t.START_MARGIN else None


def _new_exit(c: t.Candidate, cost: int, peak: int, held: int, opts: t.Options, ratio: float) -> str | None:
    verdict = t.exit_reason(c, cost, peak, held, ratio, t.Learned().min_margin, opts)
    return verdict[0] if verdict else None


def _reference_exit(c: t.Candidate, cost: int, peak: int, held: int, opts: t.Options, ratio: float) -> str | None:
    return "TURN" if c.forecast < 0 else None


STRATEGIES = {
    "none": None,
    "reference": (_reference_buy, _reference_exit, t.Options()),
    "conservative": (_new_buy, _new_exit, t.profile("conservative")),
    "balanced": (_new_buy, _new_exit, t.profile("balanced")),
    "aggressive": (_new_buy, _new_exit, t.profile("aggressive")),
}


def _windows(auctions: Sequence[Auction], first_day: int, folds: int) -> list[tuple[int, int]]:
    """Consecutive test windows over the auctions, each with at least MIN_TRAINING_DAYS of history
    before it."""
    days = sorted({a.day for a in auctions if a.day >= first_day + MIN_TRAINING_DAYS})
    if not days:
        return []
    size = max(1, len(days) // max(folds, 1))
    starts = days[::size][:folds]
    return [(start, (starts[i + 1] - 1) if i + 1 < len(starts) else days[-1]) for i, start in enumerate(starts)]


def run(
    auctions: Sequence[Auction],
    histories: Mapping[str, Sequence[Sequence[int]]],
    matches: Mapping[str, Sequence] | None = None,
    start_capital: int = 20_000_000,
    ratio: float = 0.9,
    folds: int = 3,
    strategies: Sequence[str] = tuple(STRATEGIES),
) -> dict:
    """Every strategy over the same walk-forward windows: the forecast model of a window is fitted only
    on the market values before the window starts. Positions still open at the end are valued at
    their last value times the ratio."""
    first = min((p[0][0] for p in histories.values() if p), default=None)
    if first is None or not auctions:
        return {"windows": [], "results": [], "data": {"auctions": len(auctions), "players": len(histories)},
                "note": "Zu wenig Daten für einen Backtest."}
    windows = _windows(auctions, first, folds)
    models = {}
    for start, _ in windows:
        before = {pid: [p for p in pts if p[0] < start] for pid, pts in histories.items()}
        cut = {pid: [m for m in ms if m[0] < start] for pid, ms in (matches or {}).items()}
        models[start] = coach.fit_forecast(before, cut)
    results = []
    for name in strategies:
        result = Result(name)
        for start, end in windows:
            _simulate(result, name, start, end, models[start], auctions, histories, matches or {}, start_capital, ratio)
        results.append(result.summary(start_capital * max(len(windows), 1)))
    return {
        "windows": [{"from_day": s, "to_day": e, "model_rows": models[s].rows} for s, e in windows],
        "results": results,
        "data": {"auctions": len(auctions), "players": len(histories), "start_capital_per_window": start_capital, "sell_ratio": ratio},
        "note": __doc__.split("\n\n")[2].replace("\n", " ") if __doc__ else "",
    }


def _simulate(result: Result, name: str, start: int, end: int, model: coach.ForecastModel, auctions: Sequence[Auction],
              histories: Mapping[str, Sequence[Sequence[int]]], matches: Mapping[str, Sequence], capital: int, ratio: float) -> None:
    strategy = STRATEGIES[name]
    by_day: dict[int, list[Auction]] = defaultdict(list)
    for a in auctions:
        by_day[a.day].append(a)
    cash = capital
    positions: dict[str, tuple[int, int, int]] = {} # player -> (cost, bought day, peak value)
    peak_equity = capital
    week_loss: dict[int, int] = defaultdict(int)
    for day in range(start, end + 1):
        if strategy is not None:
            buy, sell, opts = strategy
            ### Exits first, with the day's value
            for pid, (cost, bought, peak) in list(positions.items()):
                value = _value(histories.get(pid) or [], day)
                if value is None:
                    continue
                peak = max(peak, value)
                positions[pid] = (cost, bought, peak)
                c = _candidate(pid, histories.get(pid) or [], day, model, matches.get(pid), value)
                code = sell(c, cost, peak, day - bought, opts, ratio) if c is not None else None
                if code is None and day < end:
                    continue
                proceeds = int(value * ratio)
                cash += proceeds
                result.profit += proceeds - cost
                result.trades += 1
                result.hold_days += day - bought
                result.losing_trades += proceeds < cost
                result.exits[code or "END"] += 1
                week_loss[day // 7] += min(proceeds - cost, 0)
                del positions[pid]
            ### Auctions of the day, best rank first; the weekly stop-loss pauses buying
            paused = opts.stop_loss and week_loss[day // 7] <= -opts.stop_loss
            earlier = [(a.value, a.price / a.value - 1) for a in auctions if a.day < day and a.value > 0]
            bids = 0
            for a in sorted(by_day.get(day, []), key=lambda a: -a.value):
                if paused or len(positions) >= MAX_POSITIONS or bids >= opts.daily_bids or a.player_id in positions or a.value <= 0:
                    result.skipped += 1
                    continue
                ### The value in force on the auction day is known during it (set the evening before)
                c = _candidate(a.player_id, histories.get(a.player_id) or [], day, model, matches.get(a.player_id), a.value)
                if c is None:
                    result.skipped += 1
                    continue
                held_value = sum(_value(histories.get(p) or [], day) or 0 for p in positions)
                room = int((cash + held_value) * opts.profit_share / 100) - held_value
                bid = buy(c, t.winning_markups(earlier, a.value), cash - opts.reserve, room, opts, ratio)
                if bid is None:
                    result.skipped += 1
                    continue
                bids += 1
                if bid > a.price: # Above the real winner: won. A tie or less: lost
                    result.won += 1
                    cash -= bid
                    positions[a.player_id] = (bid, day, a.value)
                else:
                    result.lost += 1
        held = sum(int((_value(histories.get(p) or [], day) or 0) * ratio) for p in positions)
        result.invested_days += sum(cost for cost, _, _ in positions.values())
        equity = cash + held
        result.equity.append((day, equity))
        peak_equity = max(peak_equity, equity)
        result.max_drawdown = max(result.max_drawdown, peak_equity - equity)
    ### Every window starts with the same capital; the result adds up what each window made
    result.net += cash - capital
