"""Milestone 4 checks: the backtest replays real auctions without looking ahead, wins only above the
real winner's price, and tells the old gross-margin rule from today's net rule. Run from backend/:
python tests/check_trader_backtest.py"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import backtest as b  # noqa: E402
from core import coach  # noqa: E402
from core import trader as t  # noqa: E402

### Tomorrow's relative change = today's: a trend follower, so the forecast is easy to reason about
TREND = coach.ForecastModel(weights=(1.0, 0.0, 0.0, 0.0, 0.0), rows=1)
START = 100


def series(value: int, daily: float, days: int = 60, first: int = START - 30) -> list[list[int]]:
    points, v = [], float(value)
    for d in range(first, first + days):
        points.append([d, int(v)])
        v *= 1 + daily
    return points


### Earlier auctions of the league, won with 0.5 to 2 % markup: what the strategies bid against
PAST = [b.Auction(START - 10 + i % 8, f"old{i}", int(5_000_000 * (1.005 + i * 0.0015)), 5_000_000) for i in range(12)]


def simulate(name: str, auctions, histories, end: int = START + 20) -> b.Result:
    result = b.Result(name)
    b._simulate(result, name, START, end, TREND, [*PAST, *auctions], histories, {}, 20_000_000, 0.9)
    return result


def main() -> None:
    passed = 0

    def ok(condition: bool, label: str) -> None:
        nonlocal passed
        assert condition, label
        passed += 1

    ### 2 % a day until the auction, flat after it: +4 % over the two updates is a gross gain, but after
    ### the 90 % instant sale a loss. The old rule buys and loses money, today's rule passes on it
    rising = series(5_000_000, 0.02)
    top = rising[30][1]
    slow = {"s": [p if p[0] <= START else [p[0], top] for p in rising]}
    value_s = b._value(slow["s"], START)
    auction = [b.Auction(START, "s", value_s + 10_000, value_s)]
    ref = simulate("reference", auction, slow)
    new = simulate("balanced", auction, slow)
    ok(ref.won == 1 and ref.net < 0, f"reference buys on the gross margin and loses ({ref.net})")
    ok(new.won + new.lost == 0 and new.net == 0, "today's rule sees the net loss and does not bid")

    ### 8 % a day: net clearly positive, the balanced strategy buys and makes money; won only above
    ### the real winner's price
    fast = {"f": series(1_000_000, 0.08)}
    value_f = b._value(fast["f"], START)
    cheap = simulate("balanced", [b.Auction(START, "f", value_f, value_f)], fast)
    ok(cheap.won == 1 and cheap.net > 0, f"a strong riser is bought and sold at a profit ({cheap.net}, {dict(cheap.exits)})")
    dear = simulate("balanced", [b.Auction(START, "f", value_f * 2, value_f)], fast)
    ok(dear.won == 0 and dear.lost == 1, "below the real winner's price: lost")
    bid_used = cheap.won and simulate("balanced", [b.Auction(START, "f", value_f, value_f)], fast)
    ok(bid_used.won == 1, "reproducible")

    ### No look-ahead: what happens after the auction day does not change the decision
    crash = {"f": [p if p[0] <= START else [p[0], p[1] // 3] for p in fast["f"]]}
    after_crash = simulate("balanced", [b.Auction(START, "f", value_f, value_f)], crash)
    ok(after_crash.won == cheap.won and after_crash.lost == cheap.lost, "same bid decision with a different future")
    ok(after_crash.net < 0, "but the result follows the real future (sold at the crashed value)")

    ### A tie is lost
    tie_bid = None
    for price in range(value_f, value_f * 2, 10_000):
        r = simulate("balanced", [b.Auction(START, "f", price, value_f)], fast)
        if r.lost:
            tie_bid = price
            break
    ok(tie_bid is not None and simulate("balanced", [b.Auction(START, "f", tie_bid - 10_000, value_f)], fast).won == 1,
       "the highest price still won is one step below the first lost one")

    ### Walk-forward: every window's model only knows the days before it
    histories = {f"p{i}": series(5_000_000 + i * 100_000, 0.002 * (i % 5)) for i in range(30)}
    auctions = [b.Auction(START + i % 20, f"p{i}", 5_000_000 + i * 100_000, 5_000_000 + i * 100_000) for i in range(30)]
    out = b.run(auctions, histories, None, 20_000_000, 0.9, 3)
    ok(len(out["windows"]) == 3 and all(w["from_day"] >= START - 30 + b.MIN_TRAINING_DAYS for w in out["windows"]), out["windows"])
    ok([r["strategy"] for r in out["results"]] == list(b.STRATEGIES), "every strategy")
    ok(out["results"][0]["net_profit"] == 0, "no trading")
    ok(b.run([], histories)["results"] == [], "no auctions: no result, a note")

    ### Profiles: complete, validated, within the hard limits
    for name in t.PROFILES:
        o = t.profile(name)
        ok(t.Options.load(o.__dict__) == o, f"{name} is valid as it is")
    ok(t.profile("balanced") == t.Options(), "balanced are the defaults")
    ok(t.profile("conservative").credit_mode == 1 and t.profile("conservative").profit_share == 30, "conservative: no credit for profit trades")

    print(f"All {passed} trader backtest checks passed.")


if __name__ == "__main__":
    main()
