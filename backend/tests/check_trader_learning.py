"""Milestone 3 checks: win probability from the league's auctions, bids by expected value, the
global model with league bid heights on top, margin learning by size, forecast pause with
hysteresis, versioned states. Run from backend/: python tests/check_trader_learning.py"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import trader as t  # noqa: E402


def main() -> None:
    passed = 0

    def ok(condition: bool, label: str) -> None:
        nonlocal passed
        assert condition, label
        passed += 1

    ### 8.1 P(win): the share of won auctions whose winner paid less on top; ties lost; too few: None
    markups = [0.02, 0.04, 0.05, 0.06, 0.08, 0.10, 0.12, 0.15, 0.20, 0.30]
    ok(t.win_probability(10_000_000, 10_000_000, markups) == 0.0, "the bare value wins nothing")
    ok(t.win_probability(10_700_000, 10_000_000, markups) == 0.4, "7 % beats 0.02/0.04/0.05/0.06")
    ok(t.win_probability(10_600_000, 10_000_000, markups) == 0.3, "a tie (6 %) counts as lost")
    ok(t.win_probability(14_000_000, 10_000_000, markups) == 1.0, "40 % beats all")
    ok(t.win_probability(10_700_000, 10_000_000, markups[:5]) is None, "five auctions are no model")

    ### Price class first, the league as a fallback
    shares = [(2_000_000, 0.5)] * 8 + [(10_000_000, 0.05)] * 3
    ok(t.winning_markups(shares, 1_000_000) == [0.5] * 8, "own price class when it has enough")
    ok(len(t.winning_markups(shares, 10_000_000)) == 11, "too few in the class: the whole league")

    ### Bids by expected value: not the highest win chance, the best P(win) x (worth - bid)
    target = t.Candidate("x", 3, 10, 10, 10, 1.0, True, 0, 100_000, 1_500_000, 10_000_000, price=10_000_000)
    bid, p, ev = t.best_bid(target, 11_350_000, 20_000_000, markups)
    ok(10_000_000 < bid < 11_350_000 and 0 < p < 1 and ev > 0, (bid, p, ev))
    for other in range(10_000_000, 11_350_000, 50_000):
        q = t.win_probability(other, 10_000_000, markups) or 0
        ok(q * (11_350_000 - other) <= ev + 1, f"no other bid is better ({other})")
    ok(t.best_bid(target, 11_350_000, 10_500_000, markups)[0] <= 10_500_000, "never above the cap")
    ok(t.best_bid(target, 10_000_000, 20_000_000, markups) is None, "worth no more than the price: no bid")
    ok(t.best_bid(target, 11_350_000, 20_000_000, markups[:3]) is None, "no model: the caller falls back")

    ### 8.4 Global base, league bid heights on top, more of them with more auctions
    base = t.Learned(extra=(0.3, 0.3, 0.3), min_margin=200_000, swap_edge=120_000)
    fresh = t.Learned()
    ok(t.blend(base, replace(fresh, extra=(0.9, 0.9, 0.9))).extra == base.extra, "a new league trades with the global heights")
    busy = replace(fresh, extra=(0.9, 0.9, 0.9), won=20, lost=20)
    mixed = t.blend(base, busy).extra[0]
    ok(0.3 < mixed < 0.9 and abs(mixed - (0.3 + 0.8 * 0.6)) < 0.001, mixed)
    ok(t.blend(base, busy).min_margin == 200_000 and t.blend(base, busy).swap_edge == 120_000, "forecast and margin stay global")
    ok(t.blend(base, busy).won == 20, "the league's own auction counts")

    ### 8.3 Margin by the size of the result: a big loss weighs more than a small gain
    m = t.Learned(min_margin=200_000)
    small_loss = t.after_sale(m, -20_000).min_margin
    big_loss = t.after_sale(m, -600_000).min_margin
    small_gain = t.after_sale(m, 20_000).min_margin
    ok(200_000 < small_loss < big_loss, (small_loss, big_loss))
    ok(200_000 - small_gain < big_loss - 200_000, "a small gain does not make up for a big loss")
    ok(t.after_sale(t.Learned(min_margin=1_500_000), -10**9).min_margin == 1_500_000, "bounded")

    ### 8.2 Forecast quality: direction hits, a pause while forecasts are systematically wrong, hysteresis
    state = t.Learned()
    for _ in range(t.MIN_SAMPLES):
        state = t.after_forecast(state, 500_000, -100_000)
    ok(state.forecast_pause == 1, f"forecasts that came out negative pause the profit trading ({state.gain_ratio})")
    ok(state.direction_rate == 0.0, "no direction right")
    ratios = []
    while state.forecast_pause:
        state = t.after_forecast(state, 500_000, 500_000)
        ratios.append(state.gain_ratio)
    ok(state.gain_ratio > t.RESUME_ABOVE and any(t.PAUSE_BELOW < r <= t.RESUME_ABOVE for r in ratios), "resumes only above 0.45")
    ok(t.after_forecast(t.Learned(), 500_000, 400_000).direction_hits == 1, "a gain that came is a hit")
    shadow = t.after_forecast(t.Learned(), 500_000, 0, t.SHADOW_WEIGHT)
    real = t.after_forecast(t.Learned(), 500_000, 0)
    ok(1.0 > shadow.gain_ratio > real.gain_ratio, "paper trades move it half as much")

    ### Versioned, old states load, junk keeps the defaults
    dumped = state.dump()
    ok(dumped["version"] == t.MODEL_VERSION and t.Learned.load(dumped) == state, "round trip with a version")
    old = {k: v for k, v in dumped.items() if k not in ("version", "direction_hits", "forecast_pause")}
    ok(t.Learned.load(old).forecast_pause == 0, "a state from before milestone 3 loads")
    ok(t.Learned.load({"forecast_pause": 7}).forecast_pause == 1, "clamped")

    print(f"All {passed} trader learning checks passed.")


if __name__ == "__main__":
    main()
