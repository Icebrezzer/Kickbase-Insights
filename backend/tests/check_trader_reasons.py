"""Reason codes of the trader's decisions (E01.02): one cause per code, never "margin or budget".

    python tests/check_trader_reasons.py
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import reasons as rc  # noqa: E402
from core import trader as t  # noqa: E402

passed = 0


def ok(condition: bool, label: str) -> None:
    global passed
    if not condition:
        raise SystemExit(f"FAILED: {label}")
    passed += 1


def p(pid: str, pos: int, expected: float, **kw) -> t.Candidate:
    base = dict(average=expected, form=expected, play=1.0, fit=True, today=0, forecast=0, gain=0, value=5_000_000, team_id=pid)
    return t.Candidate(pid, pos, expected, **{**base, **kw})


def main() -> None:
    ### Every code has a German text, and the codes of core.trader are known ones
    codes = {v for k, v in vars(rc).items() if k.isupper() and isinstance(v, str)}
    ok(codes <= set(rc.TEXT), f"every code has a text ({codes - set(rc.TEXT)})")

    ### Why a target is no lineup upgrade: one code per check, lineup_upgrade unchanged
    eleven = [p("g", 1, 50), *(p(f"d{i}", 2, 60 - i * 5) for i in range(4)), *(p(f"m{i}", 3, 70 - i * 5) for i in range(4)),
              p("f0", 4, 80), p("f1", 4, 75)]
    opts = t.Options()
    cases = {
        "NOT_FIT": p("x", 3, 90, fit=False),
        "PLAY_RATE_UNKNOWN": p("x", 3, 90, play=None),
        "PLAY_RATE_LOW": p("x", 3, 90, play=0.2),
        "NO_ELEVEN_GAIN": p("x", 3, 10),
        "GAIN_BELOW_MIN": p("x", 2, 46),
        "QUALITY_UNKNOWN": p("x", 3, 90, average=None, form=None),
        "QUALITY_EDGE": p("x", 3, 90, average=10, form=10),
        "LOOKAHEAD_WORSE": p("x", 3, 90, ahead=10),
    }
    with_ahead = [replace(c, ahead=c.expected) for c in eleven]
    for code, target in cases.items():
        squad = with_ahead if code == "LOOKAHEAD_WORSE" else eleven
        up, found = t.upgrade_check(squad, target, opts)
        ok(up is None and found == code and found in rc.TEXT, f"no upgrade: {code} ({found})")
        ok(t.lineup_upgrade(squad, target, opts) is None, f"lineup_upgrade agrees: {code}")
    up, found = t.upgrade_check(eleven, p("x", 3, 90), opts)
    ok(up is not None and found is None and t.lineup_upgrade(eleven, p("x", 3, 90), opts) == up, "an upgrade has no reason code")

    ### Price blockers at the minimum bid, each cause on its own
    riser = p("r", 3, 50, value=10_000_000, price=10_000_000, bid_low=10_000_000, forecast=200_000, gain=400_000)
    ### At 90 % the forecast does not pay: margin and return; and the money is short too
    found = rc.price_blockers(riser, "profit", None, 1_000_000, opts, 150_000, 0.9, 50_000_000)
    ok(found == [rc.MARGIN_BELOW_MIN, rc.ROI_BELOW_MIN, rc.BUDGET], f"profit: what does not pay comes first ({found})")
    ### At 100 % it pays, the money alone is short
    found = rc.price_blockers(riser, "profit", None, 1_000_000, opts, 150_000, 1.0, 50_000_000)
    ok(found == [rc.BUDGET], f"profit: only the budget ({found})")
    found = rc.price_blockers(riser, "profit", None, 20_000_000, opts, 150_000, 1.0, 5_000_000)
    ok(found == [rc.PROFIT_ROOM], f"profit: the profit room ({found})")
    found = rc.price_blockers(riser, "profit", None, 20_000_000, t.Options(min_roi=5.0), 150_000, 1.0, 50_000_000)
    ok(found == [rc.ROI_BELOW_MIN], f"profit: the return alone ({found})")
    found = rc.price_blockers(replace(riser, today=-10_000), "profit", None, 20_000_000, opts, 150_000, 1.0, 50_000_000)
    ok(found == [rc.FALLING_TODAY], f"profit: fell today ({found})")
    found = rc.price_blockers(replace(riser, value=0, price=0, bid_low=0), "profit", None, 20_000_000, opts, 150_000, 1.0, 50_000_000)
    ok(found == [rc.NO_PRICE], f"no valid price ({found})")
    ### Lineup: price per point, and the lineup share of the money
    upgrade = t.Upgrade(gain=5.0, replaced="d3", replaced_value=2_000_000)
    found = rc.price_blockers(riser, "lineup", upgrade, 50_000_000, opts, 150_000, 1.0, 0)
    ok(found == [rc.PRICE_PER_POINT], f"lineup: price per point ({found})")
    cheap = t.Upgrade(gain=40.0, replaced="d3", replaced_value=9_000_000)
    found = rc.price_blockers(riser, "lineup", cheap, 12_000_000, t.Options(lineup_share=50), 150_000, 1.0, 0)
    ok(found == [rc.BUDGET], f"lineup: the lineup share leaves too little ({found})")
    found = rc.price_blockers(riser, "cover", None, 50_000_000, opts, 150_000, 1.0, 0)
    ok(found == [rc.COVER_PRICE], f"cover: above the cover price ({found})")

    ### Money limits, largest first, zero ones left out
    check = {"limits": {"profit": {t.LIMIT_RESERVE: 2_000_000, t.LIMIT_CREDIT_MODE: 12_000_000, t.LIMIT_DEBT: 0}}}
    ok(rc.money_limits(check, "profit") == [t.LIMIT_CREDIT_MODE, t.LIMIT_RESERVE], "money limits largest first")
    ok(rc.money_limits(None, "profit") == [] and rc.money_limits(check, "lineup") == [], "no check, no limits")

    print(f"All {passed} trader reason checks passed.")


if __name__ == "__main__":
    main()
