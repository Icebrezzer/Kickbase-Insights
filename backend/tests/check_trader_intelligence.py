"""Milestone 2 checks: lineup 2.0 (weighted quality, thin data, next matches, fair price per point),
priorities by phase and the exit system of profit positions. Run from backend/:
python tests/check_trader_intelligence.py"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import trader as t  # noqa: E402

OPTS = t.Options()


def p(pid: str, pos: int, expected: float, **kw) -> t.Candidate:
    base = dict(average=expected, form=expected, play=1.0, fit=True, today=0, forecast=0, gain=0, value=5_000_000, samples=5)
    return t.Candidate(pid, pos, expected, **{**base, **kw})


def squad() -> list[t.Candidate]:
    players = [p("g1", 1, 50), p("g2", 1, 20)]
    players += [p(f"d{i}", 2, 60 - i * 5) for i in range(5)]
    players += [p(f"m{i}", 3, 70 - i * 5) for i in range(6)]
    players += [p(f"f{i}", 4, 80 - i * 10) for i in range(3)] + [p("f3", 4, 5)]
    best = set(t.best_of(players).player_ids)
    return [replace(c, in_best=c.player_id in best) for c in players]


def main() -> None:
    passed = 0

    def ok(condition: bool, label: str) -> None:
        nonlocal passed
        assert condition, label
        passed += 1

    s = squad()
    star = p("s", 4, 95, average=90, form=100, value=12_000_000)

    ### 5.1 A gap is filled even with a small point gain, its price judged by the real points
    keeper = p("k", 1, 3, value=500_000)
    fill = t.lineup_upgrade([], keeper, OPTS)
    ok(fill is not None and fill.fills and fill.gain == 3, "a gap is filled though 3 points < min_gain? no: min_gain only for swaps")
    ok(t.lineup_upgrade([], replace(keeper, play=None), OPTS) is None, "but never with unknown play")

    ### 5.2/5.3 Thin data: fewer than three matches need 1.5 x min_gain
    ### A target whose swap gains between min_gain (2) and 1.5 x min_gain (3) points
    borderline = next(
        c for c in (replace(star, expected=x / 10) for x in range(0, 1000))
        if (u := t.lineup_upgrade(s, c, OPTS)) is not None and 2.0 <= u.gain < 3.0
    )
    ok(t.lineup_upgrade(s, replace(borderline, samples=1), OPTS) is None, "thin data needs 1.5 x min_gain")
    ok(t.lineup_upgrade(s, replace(borderline, samples=None), OPTS) is not None, "unknown sample size is not thin")
    ok(t.lineup_upgrade(s, replace(star, average=None, form=None), OPTS) is None, "no average and no form: no swap")
    ok(t.lineup_upgrade(s, replace(star, average=None), OPTS) is not None, "form alone is enough data")

    ### Next matches: a player who is only better this weekend is no swap
    up = t.lineup_upgrade(s, star, OPTS)
    replaced = next(c for c in s if c.player_id == up.replaced)
    s_ahead = [replace(c, ahead=c.expected) for c in s]
    ok(t.lineup_upgrade(s_ahead, replace(star, ahead=replaced.expected - 1), OPTS) is None, "worse over the next three matches")
    ok(t.lineup_upgrade(s_ahead, replace(star, ahead=replaced.expected + 5), OPTS) is not None, "better over them too")
    ok(t.lineup_upgrade(s, replace(star, ahead=None), OPTS) is not None, "unknown fixtures do not block")

    ### 5.5 Price per point: the bid minus what the replaced player would really bring (sale ratio)
    upgrade = t.Upgrade(10.0, "f2", 5_000_000)
    ok(t.cost_per_point(upgrade, 8_000_000, 0.9) == 350_000, t.cost_per_point(upgrade, 8_000_000, 0.9))
    ok(t.cost_per_point(upgrade, 8_000_000, 0.9) > t.cost_per_point(upgrade, 8_000_000, 1.0), "not as if he were sold at full value")
    ok(not t.worth_it(upgrade, 8_000_000, OPTS, 0.9) and t.worth_it(upgrade, 7_500_000, OPTS, 0.9), "300k per point limit")

    ### 6.1 Priorities by phase
    order = lambda stage: sorted(  # noqa: E731
        [("fill", True), ("lineup", False), ("profit", False), ("cover", False)],
        key=lambda x: t.priority(x[0] if x[0] != "fill" else "lineup", x[1], stage, 0.0), reverse=True,
    )
    ok([x[0] for x in order("normal")] == ["fill", "lineup", "profit", "cover"], order("normal"))
    for stage in ("prepare", "repay", "final"):
        ok([x[0] for x in order(stage)] == ["fill", "cover", "lineup", "profit"], f"{stage}: {order(stage)}")
    ok(t.priority("lineup", False, "normal", 12.0) > t.priority("lineup", False, "normal", 5.0), "within a tier: score")

    ### 7 Exits of a profit position bought at 10 Mio. (ratio 0.9, margin 150k)
    pos = p("x", 3, 10, value=12_000_000, forecast=100_000, gain=400_000)
    cost, margin = 10_000_000, 150_000

    def verdict(**kw):
        args = {"peak": None, "held": 1, **kw}
        c = replace(pos, **{k: v for k, v in kw.items() if k not in ("peak", "held", "opts")})
        result = t.exit_reason(c, cost, args["peak"], args["held"], 0.9, margin, kw.get("opts", OPTS))
        return result[0] if result else None

    ok(verdict() is None, "in profit with 360k more to come: hold")
    ok(verdict(fit=False) == "SPORT", "injured: out")
    ok(verdict(value=8_500_000, forecast=0, gain=0) == "STOP", "7.65 Mio. net for 10 Mio.: position stop-loss")
    ok(verdict(value=8_500_000, forecast=50_000, gain=200_000) is None, "a loss the forecast sees recovering is held")
    ok(verdict(value=12_500_000, peak=13_500_000, forecast=0, gain=0) == "TRAIL", "7 % below the peak")
    ok(verdict(value=12_500_000, peak=13_500_000, forecast=0, gain=0, opts=replace(OPTS, trailing_stop=0)) == "TAKE", "trailing off")
    ok(verdict(forecast=-100_000, today=-10_000, gain=-200_000) == "TURN", "turn confirmed by a fall today")
    ok(verdict(forecast=-10_000, today=20_000, gain=400_000) is None, "a tiny negative forecast alone is noise")
    ok(verdict(forecast=0, gain=100_000) == "TAKE", "in profit, holding brings 90k < margin: take it")
    ok(verdict(value=10_500_000, forecast=0, gain=100_000, held=8) == "TIME", "8 days without enough to gain")
    ok(verdict(value=10_500_000, forecast=0, gain=100_000, held=3) is None, "3 days: still in time")
    ok(verdict(value=10_500_000, forecast=0, gain=100_000, held=30, opts=replace(OPTS, max_hold_days=0)) is None, "time limit off")

    print(f"All {passed} trader intelligence checks passed.")


if __name__ == "__main__":
    main()
