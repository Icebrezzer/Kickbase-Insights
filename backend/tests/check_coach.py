"""Checks of the formulas in core/coach.py. Run from backend/: python tests/check_coach.py"""

from __future__ import annotations

import random
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import coach as c  # noqa: E402


def t(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=UTC)


def main() -> None:
    ### Deadline from the first kick-off, also when the matchday starts on a Friday
    fixtures = [
        c.FixtureInfo(12, t(22, 14, 30), 2, "1", "2"),
        c.FixtureInfo(13, t(28, 14, 30), 0, "1", "3"),
        c.FixtureInfo(13, t(27, 19, 30), 0, "2", "4"),
    ]
    upcoming = c.next_matchday(fixtures, t(27, 12))
    assert upcoming and upcoming.day == 13 and upcoming.deadline == t(27, 19, 29), upcoming
    assert c.lineup_open(fixtures, t(27, 12))
    assert c.live_matchday(fixtures, t(27, 20)) == 13
    assert not c.lineup_open(fixtures, t(27, 20))
    assert c.updates_until(t(27, 19, 29), t(23, 8)) == 4

    ### Expected points
    placements = {"1": 1, "2": 5, "3": 18, "4": 10}
    weak = c.expected_points(c.FormInput("p", 3, 0, "1", 120, (200, 80, 0, 150, 100)), c.next_fixture_of("1", fixtures, 13), placements)
    assert weak.opponent_factor > 1.15 and weak.home is True, weak
    injured = c.expected_points(c.FormInput("q", 3, 1, "2", 150), c.next_fixture_of("2", fixtures, 13), placements)
    assert injured.expected == 0 and "verletzt" in injured.reasons
    assert abs(c.opponent_factor(1, 18, None) - 0.85) < 1e-9 and abs(c.opponent_factor(18, 18, None) - 1.15) < 1e-9

    ### Best eleven: full, best formation, keeps the saved one on a tie
    rng = random.Random(1)
    positions = [1, 1, 2, 2, 2, 2, 2, 3, 3, 3, 3, 3, 3, 4, 4, 4]
    squad = [c.SellCandidate(f"p{i}", pos, rng.randint(20, 200), rng.randint(1, 20) * 1_000_000) for i, pos in enumerate(positions)]
    eleven = c.best_eleven([c.LineupCandidate(s.player_id, s.position, s.expected, s.value) for s in squad])
    assert len(eleven.player_ids) == 11 and eleven.empty_slots == 0, eleven
    tie = c.best_eleven([c.LineupCandidate("a", 1, 50), c.LineupCandidate("b", 1, 50)] , keep=["b"])
    assert tie.player_ids[0] == "b", tie

    ### Budget rescue sells bench players first and reaches zero
    plan = c.rescue_sales(-12_000_000, squad)
    assert plan.enough and plan.budget_after >= 0, plan
    bench = set(s.player_id for s in squad) - set(eleven.player_ids)
    assert set(plan.sales) <= bench or plan.expected_loss < 50, plan
    hopeless = c.rescue_sales(-10**10, squad)
    assert not hopeless.enough

    ### Forecast learns an AR(1) process
    histories = []
    for _ in range(300):
        value, drift, points = rng.randint(1, 30) * 1_000_000, 0.0, []
        for day in range(20300, 20420):
            drift = 0.8 * drift + rng.gauss(0, 0.01)
            value = int(value * (1 + drift))
            points.append([day, value])
        histories.append(points)
    model = c.fit_forecast(histories)
    assert model.learned and 0.7 < model.weights[0] < 0.9, model
    assert model.error is not None and model.naive_error is not None and model.error < model.naive_error
    rising = [[20400 + i, 1_000_000 + i * 50_000] for i in range(12)]
    prediction = c.forecast(rising)
    assert prediction and prediction.next_change > 0 and len(prediction.projection) == 3 and prediction.streak == 11
    assert c.forecast(rising[:5]) is None

    ### Club limit and rivals
    clubs = c.ClubCounts.build([("a", "1"), ("a", "1"), ("a", "1"), ("b", "1"), ("c", "2")])
    assert not clubs.can_buy("a", "1") and clubs.can_buy("b", "1")
    rich = c.rivals_for("1", 5_000_000, ["a", "b", "c"], clubs, {"a": 9_000_000, "b": 4_000_000, "c": 10_000_000})
    assert [r.manager_id for r in rich] == ["c"], rich
    plain = c.rivals_for("1", 5_000_000, ["a", "b", "c"], clubs)
    assert {r.manager_id for r in plain} == {"b", "c"}, plain

    print("All coach checks passed.")


if __name__ == "__main__":
    main()
