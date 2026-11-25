"""Checks of the autotrader decisions in core/trader.py. Run from backend/: python tests/check_trader.py"""

from __future__ import annotations

import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import coach  # noqa: E402
from core import trader as t  # noqa: E402

OPTS = t.Options()


def p(pid: str, pos: int, expected: float, **kw) -> t.Candidate:
    base = dict(average=expected, form=expected, play=1.0, fit=True, today=0, forecast=0, gain=0, value=5_000_000)
    return t.Candidate(pid, pos, expected, **{**base, **kw})


def squad() -> list[t.Candidate]:
    """2 GK, 5 DEF, 6 MID, 4 FW: whatever the best eleven fields, one fit substitute per position is left."""
    players = [p("g1", 1, 50), p("g2", 1, 20)]
    players += [p(f"d{i}", 2, 60 - i * 5) for i in range(5)]
    players += [p(f"m{i}", 3, 70 - i * 5) for i in range(6)]
    players += [p(f"f{i}", 4, 80 - i * 10) for i in range(3)] + [p("f3", 4, 5)]
    best = set(t.best_of(players).player_ids)
    return [replace(c, in_best=c.player_id in best) for c in players]


def main() -> None:
    s = squad()
    by = {c.player_id: c for c in s}

    ### Options: missing keys take the defaults, everything is clamped, junk is ignored
    o = t.Options.load({"min_gain": "7.5", "daily_bids": 999, "sell_window": 1, "nonsense": 1, "reserve": "x", "shadow": 0})
    assert (o.min_gain, o.daily_bids, o.sell_window, o.reserve, o.shadow) == (7.5, 30, 5, 0, False), o
    assert t.Options.load(None) == OPTS
    assert set(t.OPTION_LIMITS) | {"shadow"} == {f for f in OPTS.__dataclass_fields__}

    ### Cover: the second goalkeeper is the only substitute, he stays; an injured one may always go
    assert not t.keeps_cover(s, by["g2"])
    assert t.keeps_cover(s, replace(by["g2"], fit=False))
    assert t.missing_cover(s) == [], t.missing_cover(s)

    ### Sell order: injured first, then non-regulars, then the bench by the weakest rise
    hurt = replace(by["m5"], fit=False)
    rare = replace(by["d4"], play=0.2)
    order = t.sell_order([by["m4"], rare, hurt], 0.6)
    assert [c.player_id for c in order] == ["m5", "d4", "m4"], [c.player_id for c in order]

    ### A rising target only displaces a bench player who clearly rises less (the learned edge)
    target = p("x", 3, 10, forecast=300_000, today=200_000)
    slow = [replace(c, forecast=50_000) if c.player_id == "m5" else c for c in s]
    sale = t.pick_sale(slow, target, 0.6, 100_000)
    assert sale is not None and not sale.in_best, sale
    assert t.pick_sale(slow, target, 0.6, 400_000) is None, "a bigger learned edge blocks the swap"
    assert t.pick_sale([replace(c, locked=True) for c in slow], target, 0.6, 100_000) is None, "locked stays"

    ### Starters: kept from `starter_lock` before the first kick-off until 5 minutes after it
    kickoff = datetime(2026, 11, 27, 19, 30, tzinfo=UTC) # Friday 20:30 in Germany
    fixtures = [coach.FixtureInfo(13, kickoff, 0, "1", "2"), coach.FixtureInfo(13, kickoff + timedelta(days=1), 0, "3", "4")]
    assert not t.starters_locked(fixtures, kickoff - timedelta(minutes=61), 60)
    assert t.starters_locked(fixtures, kickoff - timedelta(minutes=59), 60)
    assert t.starters_locked(fixtures, kickoff + timedelta(minutes=4), 60)
    assert not t.starters_locked(fixtures, kickoff + timedelta(minutes=5), 60), "free again from 20:35"
    assert not t.starters_locked(fixtures, kickoff + timedelta(days=1, minutes=10), 60), "only the first kick-off counts"

    ### Lineup upgrade: more points, a proven regular, clearly better average, better form
    star = p("s", 4, 95, average=90, form=100, value=12_000_000)
    up = t.lineup_upgrade(s, star, OPTS)
    assert up and up.gain >= OPTS.min_gain and up.replaced in {"f0", "f1", "f2", "m3", "m4"}, up
    assert t.lineup_upgrade(s, replace(star, play=None), OPTS) is None, "unknown play counts as no regular"
    assert t.lineup_upgrade(s, replace(star, play=0.2), OPTS) is None, "no regular, no buy"
    assert t.lineup_upgrade(s, replace(star, fit=False), OPTS) is None, "injured, no buy"
    assert t.lineup_upgrade(s, replace(star, form=1), OPTS) is None, "worse recent form, no buy"
    assert t.lineup_upgrade(s, star, replace(OPTS, min_gain=500)) is None, "the minimum gain is a setting"
    replaced = by[up.replaced]
    near = replace(star, average=replaced.average * 1.05)
    assert t.lineup_upgrade(s, near, OPTS) is None, "5 % better average is not clearly better"
    assert t.lineup_upgrade(s, near, replace(OPTS, min_avg_edge=0)) is not None

    ### Price/performance: 15 Mio. more for 2 points is not worth it, for 60 points it is
    small = t.Upgrade(2.0, "f2", 5_000_000)
    assert not t.worth_it(small, 20_000_000, OPTS), t.cost_per_point(small, 20_000_000)
    big = t.Upgrade(60.0, "f2", 5_000_000)
    assert t.worth_it(big, 20_000_000, OPTS), t.cost_per_point(big, 20_000_000)
    assert t.worth_it(small, 5_400_000, OPTS), "cheaper than the replaced player plus 400k"

    ### Cover: a missing substitute is filled by the cheapest fit, playing, not falling player
    no_keeper = [c for c in s if c.player_id != "g2"]
    assert t.missing_cover(no_keeper) == [1]
    market = [
        p("k1", 1, 10, play=0.4, value=800_000, price=800_000, bid_low=820_000),
        p("k2", 1, 30, play=0.8, value=2_000_000, price=2_000_000, bid_low=2_050_000),
        p("k3", 1, 30, play=0.0, value=500_000, price=500_000, bid_low=510_000),
        p("k4", 1, 30, play=1.0, value=900_000, price=900_000, forecast=-50_000),
        p("k5", 1, 30, play=1.0, value=9_000_000, price=9_000_000),
    ]
    chosen = t.cover_target(no_keeper, market, OPTS)
    assert chosen is not None and chosen.player_id == "k1", chosen

    ### The price: between low and high by the learned extra, capped, and a profit buy keeps half the gain
    m = p("m", 3, 10, value=10_000_000, price=10_000_000, bid_low=10_300_000, bid_high=11_000_000, gain=800_000, forecast=400_000)
    assert t.bid_for(m, 0.0, None, profit=False) == 10_300_000
    assert t.bid_for(m, 1.0, None, profit=False) == 11_000_000
    assert t.bid_for(m, 1.0, None, profit=True) == 10_400_000, t.bid_for(m, 1.0, None, profit=True)
    assert t.bid_for(m, 0.0, 10_000_000, profit=False) is None, "cap below the minimum"
    assert t.is_profit_buy(m, 10_300_000, 150_000)
    assert not t.is_profit_buy(replace(m, today=-10_000), 10_300_000, 150_000), "falling today"

    ### Learning: lost raises the bid of that price class, won lowers it; shadows count half
    state = t.Learned()
    lost = t.after_auction(state, 10_000_000, False, 10_300_000, 10_900_000)
    assert lost.extra[1] > state.extra[1] and lost.lost == 1
    won = t.after_auction(lost, 10_000_000, True, 10_300_000, None)
    assert won.extra[1] < lost.extra[1] and won.won == 1
    paper = t.after_auction(state, 10_000_000, False, 10_300_000, 10_900_000, t.SHADOW_WEIGHT)
    assert state.extra[1] < paper.extra[1] < lost.extra[1] and paper.shadow_lost == 1 and paper.lost == 0
    assert t.after_sale(state, -200_000).min_margin > state.min_margin > t.after_sale(state, 300_000).min_margin
    assert t.Learned.load(won.dump()) == won
    assert t.Learned.load({"extra": [1, 2], "gain_ratio": "bad"}) == t.Learned(), "broken state falls back"

    ### Forecast trust: only used after enough observations, and bounded
    trust = state
    for _ in range(t.MIN_SAMPLES - 1):
        trust = t.after_forecast(trust, 500_000, 100_000)
    assert trust.gain_scale == 1.0, "not enough samples yet"
    trust = t.after_forecast(trust, 500_000, 100_000)
    assert 0.3 <= trust.gain_scale < 1.0, trust.gain_scale
    assert t.after_forecast(state, 10_000, 900_000) == state, "tiny forecasts teach nothing"

    ### Regret: sold players who rose afterwards make swaps stricter
    assert t.after_regret(state, 400_000).swap_edge > state.swap_edge > t.after_regret(state, -50_000).swap_edge

    ### Weekly statistics, with the paper trades
    monday = datetime(2026, 11, 23, 12, tzinfo=UTC)
    weeks = t.weekly([
        t.Trade(monday, "bid", "won", 10_300_000, paid=10_300_000, points_gain=12.5),
        t.Trade(monday, "bid", "lost", 5_000_000),
        t.Trade(monday, "bid", "planned", 5_000_000),
        t.Trade(monday, "sell", "sold", 11_000_000, profit=700_000),
        t.Trade(monday, "shadow", "done", 3_000_000, profit=250_000),
        t.Trade(monday, "shadow", "holding", 3_000_000),
        t.Trade(datetime(2026, 11, 16, tzinfo=UTC), "sell", "sold", 4_000_000, profit=-100_000),
    ])
    assert [w["week"] for w in weeks] == ["2026-W48", "2026-W47"], weeks
    w = weeks[0]
    assert (w["bids"], w["won"], w["lost"], w["planned"], w["spent"], w["profit"], w["points_gain"]) == (
        2, 1, 1, 1, 10_300_000, 700_000, 12.5
    ), w
    assert (w["shadow_trades"], w["shadow_profit"]) == (1, 250_000), w
    print("All trader checks passed.")


if __name__ == "__main__":
    main()
