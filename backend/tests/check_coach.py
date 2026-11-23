"""Checks of the formulas in core/coach.py. Run from backend/: python tests/check_coach.py"""

from __future__ import annotations

import random
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import achievements as a  # noqa: E402
from core import coach as c  # noqa: E402
from core import learning as ln  # noqa: E402


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
    ### A replay three weeks later does not block the lineup of the matchday in between
    replay = [*fixtures, c.FixtureInfo(12, datetime(2026, 12, 16, 19, 30, tzinfo=UTC), 0, "5", "6")]
    assert c.live_matchday(replay, t(25, 12)) is None and c.lineup_open(replay, t(25, 12))

    ### Expected points
    placements = {"1": 1, "2": 5, "3": 18, "4": 10}
    recent = tuple(c.MatchForm(p, 90, c.ROLE_START) for p in (200, 80, 0, 150, 100))
    weak = c.expected_points(c.FormInput("p", 3, 0, "1", 120, recent), c.next_fixture_of("1", fixtures, 13), placements)
    assert weak.opponent_factor > 1.15 and weak.home is True and weak.play_probability == 1.0, weak
    ### Benched four times out of five: far fewer points, and said why
    benched = (c.MatchForm(150, 90, c.ROLE_START), *(c.MatchForm(0, 0, c.ROLE_BENCH) for _ in range(4)))
    rotation = c.expected_points(c.FormInput("r", 3, 0, "1", 120, benched), c.next_fixture_of("1", fixtures, 13), placements)
    assert rotation.play_probability == 0.2 and rotation.expected < weak.expected / 3, rotation
    assert "selten in der Startelf" in rotation.reasons
    ### Odds win over the table: a big favourite gets more than an outsider
    favourite = c.expected_points(c.FormInput("f", 3, 0, "1", 120, recent), c.next_fixture_of("1", fixtures, 13), placements, 0.8)
    outsider = c.expected_points(c.FormInput("o", 3, 0, "1", 120, recent), c.next_fixture_of("1", fixtures, 13), placements, 0.1)
    assert favourite.expected > outsider.expected and favourite.win_probability == 0.8
    probabilities = c.win_probabilities(1.68, 4.0, 3.7)
    assert probabilities and abs(sum(probabilities) - 1) < 1e-9 and probabilities[0] > 0.5
    assert c.find_odds({"it": [{"o": "1.68"}, {"o": 4.0}, {"o": 3.7}]}) == (1.68, 4.0, 3.7)
    assert c.find_odds({"odds": {"1": 1.5, "X": "4,1", "2": 6}}) == (1.5, 4.1, 6.0)
    assert c.find_odds({"link": "https://example.org"}) is None
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
    model = c.fit_forecast(dict(enumerate(histories)))
    assert model.learned and 0.7 < model.weights[0] < 0.9, model
    assert model.error is not None and model.naive_error is not None and model.error < model.naive_error
    rising = [[20400 + i, 1_000_000 + i * 50_000] for i in range(12)]
    prediction = c.forecast(rising)
    assert prediction and prediction.next_change > 0 and len(prediction.projection) == 3 and prediction.streak == 11
    assert c.forecast(rising[:5]) is None

    ### Match points: a value that rises after big matchdays is learned
    with_points, matches = {}, {}
    for index in range(300):
        value, points, games = rng.randint(2, 30) * 1_000_000, [], []
        for day in range(20300, 20420):
            if day % 7 == 0:
                games.append((day, rng.choice([0, 50, 100, 200, 300])))
            recent_points = sum(p for d, p in games if day - 3 < d <= day)
            value = int(value * (1 + rng.gauss(0, 0.004) + recent_points / 1000 * 0.02))
            points.append([day, value])
        with_points[str(index)], matches[str(index)] = points, games
    learned = c.fit_forecast(with_points, matches)
    assert learned.weights[4] > 0.005, learned
    shifted = list(with_points["0"])
    last_day = shifted[-1][0]
    hot = c.forecast(shifted, learned, matches=[(last_day, 300)])
    cold = c.forecast(shifted, learned, matches=[(last_day, 0)])
    assert hot and cold and hot.next_change > cold.next_change

    ### Bidders and bid range
    profile = c.BidderProfile("m", (0.05, 0.1, 0.2, 0.08), (4_000_000, 6_000_000, 7_000_000, 8_000_000), 3, {1: 1, 2: 5, 3: 6, 4: 2}, 16)
    keen = c.estimate_bidder(profile, 1, 6_000_000, 6_000_000, True, 20_000_000, [0.05])
    assert keen.probability > 0.5 and keen.expected_bid and keen.expected_bid > 6_000_000, keen
    assert c.estimate_bidder(profile, 1, 6_000_000, 6_000_000, False, None).probability == 0
    assert c.estimate_bidder(profile, 1, 6_000_000, 6_000_000, True, 5_000_000).probability == 0
    bids = c.bid_range(6_000_000, 6_000_000, [0.03, 0.05, 0.07], [keen], 400_000, 30_000_000)
    assert bids.low >= 6_000_000 and bids.high > keen.expected_bid and bids.beats == ("m",), bids
    assert bids.margin_low is not None and bids.margin_low > bids.margin_high  # type: ignore[operator]
    capped = c.bid_range(6_000_000, 6_000_000, [0.03], [keen], None, 6_100_000)
    assert capped.high <= 6_100_000 and capped.low <= capped.high

    ### Sell advice and buy planner
    assert c.sell_advice("x", (-120_000, -250_000, -300_000), 2, False) is not None
    assert c.sell_advice("x", (-120_000, -250_000, -300_000), 2, True) is None
    assert c.sell_advice("x", (50_000, 80_000), 2, False) is None
    lineup = [c.LineupCandidate(s.player_id, s.position, s.expected, s.value) for s in squad]
    assert c.points_gain(lineup, c.LineupCandidate("star", 4, 500)) > 0
    assert c.points_gain(lineup, c.LineupCandidate("dud", 4, 1)) == 0

    ### Club limit and rivals
    clubs = c.ClubCounts.build([("a", "1"), ("a", "1"), ("a", "1"), ("b", "1"), ("c", "2")])
    assert not clubs.can_buy("a", "1") and clubs.can_buy("b", "1")
    rich = c.rivals_for("1", 5_000_000, ["a", "b", "c"], clubs, {"a": 9_000_000, "b": 4_000_000, "c": 10_000_000})
    assert [r.manager_id for r in rich] == ["c"], rich
    plain = c.rivals_for("1", 5_000_000, ["a", "b", "c"], clubs)
    assert {r.manager_id for r in plain} == {"b", "c"}, plain

    ### Achievements: BaseXI's figures for the league leader in November 2026 (41.9 Mio incl. 1 Mio
    ### "Tormaschine", which cannot be worked out from the stored data)
    day_points = [1180, 980, 780, 2067, 1380, 1620, 1490, 980, 1990, 1720]
    placements = [1, 3, 5, 1, 2, 1, 1, 4, 1, 1]
    values = [120e6, 180e6, 230e6, 280e6, 300e6, 330e6, 360e6, 390e6, 400e6, 415.2e6]
    lineup_points = {
        1: [663, 120], 2: [210, 90], 3: [150], 4: [520, 410, 230], 5: [310, 205], 6: [240, 100], 7: [205],
        8: [180], 9: [330, 300, 260], 10: [505, 420, 330],
    }
    season = a.ManagerSeason(
        "m",
        [(d + 1, p, pl, int(v)) for d, (p, pl, v) in enumerate(zip(day_points, placements, values, strict=True))],
        14306,
        lineup_points,
        mvp_days=3,
        profits=[3.2e6] * 10 + [5.5e6] * 8 + [1.5e6],
        transfers=315,
        squad_size=14,
    )
    earned = {e.rule.key: e for e in a.evaluate(season)}
    assert earned["md_win"].count == 6 and earned["md_win_3"].count == 1 and earned["md_win_10"].count == 0
    assert earned["md_1000"].count == 7 and earned["md_1500"].count == 4 and earned["md_2000"].count == 1
    assert earned["goals"].count is None
    by_group: dict[str, int] = {}
    for e in earned.values():
        by_group[e.rule.group] = by_group.get(e.rule.group, 0) + e.amount
    assert by_group["Spieltagssiege"] == 7_500_000, by_group
    assert by_group["Spieltagspunkte"] == 7_850_000, by_group
    assert by_group["Saisonpunkte"] == 350_000, by_group
    assert by_group["Mannschaftswert"] == 3_850_000, by_group
    assert by_group["Transfers & Händchen"] == 8_700_000, by_group
    assert by_group["Transferkönig"] == 750_000, by_group
    assert a.total(list(earned.values())) == sum(by_group.values())
    assert a.mvp_days({1: ["x", "y"], 2: ["z"]}, {1: {"y"}, 2: {"q"}}) == 1

    ### Learning: expected points weights are recovered from points made with known weights
    truth = c.ExpectationWeights(form=0.8, average=0.2, win=0.6, table=0.1)
    rows = []
    for _ in range(1500):
        form, average = rng.uniform(20, 250), rng.uniform(30, 200)
        win = rng.choice([None, rng.uniform(0.1, 0.8)])
        row = ln.ExpectationRow(form, average, rng.choice([1.0, 0.8, 0.5]), win, rng.uniform(-1, 1), rng.choice([True, False]), 0)
        actual = ln.predict(row, truth) + rng.gauss(0, 15)
        rows.append(ln.ExpectationRow(row.form, row.average, row.chance, row.win, row.table, row.home, int(actual)))
    fitted = ln.fit_expectation(rows)
    assert fitted.learned and abs(fitted.form - 0.8) < 0.1 and abs(fitted.average - 0.2) < 0.1, fitted
    assert fitted.error is not None and fitted.default_error is not None and fitted.error < fitted.default_error
    assert not ln.fit_expectation(rows[:100]).learned
    matches = [[d, p, 90, 5] for d, p in zip(range(1, 9), (100, 120, 80, 150, 0, 200, 90, 110), strict=True)]
    history = ln.history_rows(matches, {d: ("3", d % 2 == 0) for d in range(1, 9)}, {"3": 18})
    assert len(history) == 5 and history[0].actual == 150 and history[0].table == 1.0

    ### Learning: the bidder model finds that need decides who wins
    samples = []
    for _ in range(400):
        need = rng.random()
        samples.append(([need, rng.random(), rng.random(), 0.0], 1 if rng.random() < need * 0.8 else 0))
    bidders = ln.fit_bidders(samples, auctions=80)
    assert bidders.learned and bidders.weights[0] > 1, bidders
    assert bidders.probability([1, 0.5, 0.5, 0]) > bidders.probability([0, 0.5, 0.5, 0])
    assert not ln.fit_bidders(samples, auctions=10).learned

    ### Learning: achievements, sales, lost auctions
    counts = ln.parse_achievement_counts({"it": [{"n": "Topscorer (100 Tsd.)", "c": 9}, {"ti": "MVP", "cnt": 3}]})
    assert counts == {"Topscorer (100 Tsd.)": 9, "MVP": 3}, counts
    assert ln.rule_for("Topscorer (100 Tsd.)") == "player_200" and ln.rule_for("Spieltagssieger Gold") == "md_win_10"
    assert ln.mode_votes({"player_200": 3}, {"player_200": 2}, {"player_200": 3}) == (0, 1)
    assert ln.mode_votes({"player_200": 2}, {"player_200": 2}, {"player_200": 3}) == (1, 0)
    assert ln.mode_votes({"player_200": 1}, {"player_200": 1}, {"player_200": 1}) == (0, 0)
    assert ln.sell_ratio([(9_500_000, 10_000_000), (4_800_000, 5_000_000)]) == 0.955
    assert ln.lost_gaps([(6_000_000, 6_000_000, 6_600_000), (7_000_000, 7_000_000, 7_350_000)]) == {1: 0.075}
    raised = c.bid_range(6_000_000, 6_000_000, [0.03], [], None, None, lost_gap=0.2)
    assert raised.high >= raised.low * 1.19, raised

    print("All coach checks passed.")


if __name__ == "__main__":
    main()
