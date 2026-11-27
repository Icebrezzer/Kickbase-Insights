"""Forecast quality on every observed player (E10.00): settling, statistics, day boundaries.

    python tests/check_trader_forecast_quality.py
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import analytics, learning  # noqa: E402

passed = 0


def ok(condition: bool, label: str) -> None:
    global passed
    if not condition:
        raise SystemExit(f"FAILED: {label}")
    passed += 1


def main() -> None:
    ### Settling: exact days only, a gap is no change, given up once the history is past both horizons
    points = [[100, 1_000_000], [101, 1_020_000], [102, 1_050_000]]
    ok(learning.settle_observation(points, 100, 1_000_000) == (20_000, 50_000, True), "both horizons known")
    ok(learning.settle_observation(points[:2], 100, 1_000_000) == (20_000, None, False), "second update still to come")
    ok(learning.settle_observation(points[:1], 100, 1_000_000) == (None, None, False), "nothing new yet")
    gap = [[100, 1_000_000], [102, 1_050_000], [103, 1_060_000]]
    ok(learning.settle_observation(gap, 100, 1_000_000) == (None, 50_000, True), "a gap is unknown, not zero; given up after it")
    ok(learning.settle_observation([[101, 990_000], [102, 980_000], [103, 970_000]], 100, 1_000_000) == (-10_000, -20_000, True),
       "without the day itself the stored value is the base")
    ok(learning.settle_observation([], 100, 1_000_000) == (None, None, False), "no history: still open")

    ### Statistics: direction, calibration, errors apart for rising and falling forecasts
    rows = [
        (1_000_000, 10_000, 20_000, 9_000, 18_000), # rising, right
        (1_000_000, 10_000, 20_000, -5_000, -6_000), # rising, wrong
        (2_000_000, -20_000, -40_000, -30_000, None), # falling, right, second update unknown
        (1_000_000, 0, 0, 1_000, 2_000), # no forecast: no direction, counted in the error
        (0, 5_000, 5_000, 5_000, 5_000), # no value: left out
    ]
    q = learning.forecast_quality(rows)
    h1, h2 = q["h1"], q["h2"]
    ok(h1["n"] == 4 and h1["direction_n"] == 3 and h1["direction_hits"] == 2, f"direction hits ({h1})")
    ok(h1["hit_rate"] == round(2 / 3, 3), "hit rate")
    ok(h1["rising"]["n"] == 2 and h1["rising"]["ratio"] == round(4_000 / 20_000, 3), "calibration of rising forecasts")
    ok(h1["falling"]["n"] == 1 and h1["falling"]["ratio"] == 1.5, "calibration of falling forecasts")
    ok(h1["rising"]["error_pct_min"] == -1.5, "worst error of a rising forecast in percent of the value")
    ok(h2["n"] == 3 and h2["falling"]["n"] == 0 and h2["falling"]["ratio"] is None, "an unknown second update is left out")
    ok(round(h1["mae_pct"], 3) == round((0.1 + 1.5 + 0.5 + 0.1) / 4, 3), f"mean absolute error ({h1['mae_pct']})")
    empty = learning.forecast_quality([])
    ok(empty["h1"]["n"] == 0 and empty["h1"]["hit_rate"] is None and empty["h1"]["mae_pct"] is None, "no data: nothing claimed")

    ### Day boundaries: an observation belongs to the market value day in force, which changes at
    ### 22:00 Berlin, in winter and in summer time
    for month, offset in ((1, 1), (7, 2)):
        before = analytics.market_value_day(datetime(2026, month, 10, 21 - offset, 59, tzinfo=UTC))
        after = analytics.market_value_day(datetime(2026, month, 10, 22 - offset, 0, tzinfo=UTC))
        ok(after == before + 1, f"the day changes at 22:00 Berlin (month {month})")

    print(f"All {passed} forecast quality checks passed.")


if __name__ == "__main__":
    main()
