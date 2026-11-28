"""Financing (E04.01, E04.03-E04.06, E04.10): scenarios, conditional collateral, register, risk engine.

    python tests/check_trader_finance.py
"""

from __future__ import annotations

import random
import sys
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import finance, risk  # noqa: E402
from core import trader as t  # noqa: E402

NOW = datetime(2026, 11, 23, 10, 0, tzinfo=UTC) # A Monday morning
passed = 0


def ok(condition: bool, label: str) -> None:
    global passed
    if not condition:
        raise SystemExit(f"FAILED: {label}")
    passed += 1


def p(pid: str, pos: int, expected: float, **kw) -> t.Candidate:
    base = dict(average=expected, form=expected, play=1.0, fit=True, today=0, forecast=0, gain=0, value=10_000_000, team_id=pid)
    return t.Candidate(pid, pos, expected, **{**base, **kw})


@dataclass
class A:
    kind: str
    purpose: str
    player_id: str
    price: int


def eleven() -> list[t.Candidate]:
    team = [p("g1", 1, 50), p("g2", 1, 10), *(p(f"d{i}", 2, 60 - i) for i in range(5)), *(p(f"m{i}", 3, 60 - i) for i in range(5)),
            p("f1", 4, 70), p("f2", 4, 65), p("f3", 4, 20)]
    best = set(t.best_of(team).player_ids)
    return [replace(c, in_best=c.player_id in best) for c in team]


def ctx(squad, listings, **kw) -> risk.Context:
    base = dict(now=NOW, switches_on=True, deadline=None, budget=0, reserve=0, credit=0, credit_mode=1, open_bids={}, trader_bids=set(),
                squad=squad, listings=listings, club_of={}, max_squad=30, max_club=9, bids_left=10, sales_left=3, ratio=1.0,
                min_margin=0, min_roi=0.0)
    return risk.Context(**{**base, **kw})


def main() -> None:
    ### E04.01: the "current" scenario is the liquidation of 2.0 exactly
    rng = random.Random(5)
    for _ in range(300):
        team = [p(f"r{i}", rng.choice((1, 2, 3, 3, 4)), rng.randrange(0, 100), fit=rng.random() > 0.1, locked=rng.random() < 0.2,
                  value=rng.randrange(500_000, 30_000_000, 10_000), forecast=rng.randrange(-400_000, 400_000, 10_000)) for i in range(rng.randrange(8, 17))]
        best = set(t.best_of(team).player_ids)
        team = [replace(c, in_best=c.player_id in best) for c in team]
        ratio, sales, bench = rng.choice((0.9, 1.0)), rng.randrange(0, 5), rng.choice((t.BENCH_FULL, t.BENCH_MINIMAL, t.BENCH_NONE))
        ok(finance.liquidation(team, ratio, sales, bench, "current") == t.liquidation_value(team, ratio, sales, bench), "current = 2.0")
        ok(finance.liquidation(team, ratio, sales, bench, "pessimistic") <= finance.liquidation(team, ratio, sales, bench, "current"),
           "pessimistic never above current")

    ### E04.03: scenarios of one sale
    riser = p("x", 3, 50, forecast=300_000)
    faller = p("y", 3, 50, forecast=-300_000)
    ok(finance.sale_value(riser, 1.0, "optimistic", 2) == 10_600_000 and finance.sale_value(riser, 1.0, "realistic", 2, 0.5) == 10_300_000, "optimistic, realistic")
    ok(finance.sale_value(riser, 1.0, "pessimistic", 2) == int(10_000_000 * (1 - 0.02 * 3)), "pessimistic rising: 2 % per update plus a buffer update")
    ok(finance.sale_value(faller, 1.0, "pessimistic", 2) == int(9_700_000 * (1 - 0.04 * 3)), "pessimistic falling: the fall, then 4 % per update")
    ok(finance.sale_value(replace(riser, value=100_000), 1.0, "pessimistic", 60) == 0, "never below zero")
    ok(finance.sale_value(riser, 0.9, "pessimistic") < finance.sale_value(riser, 1.0, "pessimistic"), "a lower sale ratio brings less")
    ok(finance.updates_between(NOW, NOW + timedelta(days=6)) == 6 and finance.updates_between(NOW, NOW + timedelta(hours=1)) == 0, "updates counted at 22:00")

    ### E04.04: a profit target pays back its own bid, if it can be sold well before the repay phase
    repay = NOW + timedelta(days=6)
    target = p("t", 3, 30, forecast=500_000, expires_at=NOW + timedelta(hours=10))
    own_back = finance.self_collateral(target, 1.0, NOW, repay)
    ok(own_back is not None and own_back.kind == "self" and own_back.value == finance.sale_value(target, 1.0, "pessimistic", 6), "six days ahead: it backs its bid")
    ok(own_back.sell_from == target.expires_at + t.MIN_HOLD, "only after the holding time of own buys")
    ok(finance.self_collateral(target, 1.0, NOW, NOW + timedelta(hours=24)) is None, "24 hours ahead: holding time plus margin do not fit")
    ok(finance.self_collateral(target, 1.0, NOW, None) is None, "unknown deadline: no collateral")
    ok(finance.self_collateral(replace(target, fit=False), 1.0, NOW, repay) is None and finance.self_collateral(replace(target, forecast=0), 1.0, NOW, repay) is None,
       "unfit or not rising: no collateral")

    ### E04.05: the starter pushed out pays back a lineup bid, and stays protected until the target is won
    team = eleven()
    star = p("s", 3, 90, expires_at=NOW + timedelta(hours=5))
    weakest_mid = min((c for c in team if c.position == 3 and c.in_best), key=lambda c: c.expected)
    back = finance.replaced_collateral(team, star, weakest_mid.player_id, 1.0, t.BENCH_FULL, NOW, repay)
    ok(back is not None and back.kind == "replaced" and back.player_id == weakest_mid.player_id, "the starter pushed out backs the bid")
    locked_team = [replace(c, locked=c.player_id == weakest_mid.player_id) for c in team]
    ok(finance.replaced_collateral(locked_team, star, weakest_mid.player_id, 1.0, t.BENCH_FULL, NOW, repay) is None, "a locked starter backs nothing")
    new_keeper = p("k", 1, 90, expires_at=NOW + timedelta(hours=5))
    ok(finance.replaced_collateral(team, new_keeper, "g1", 1.0, t.BENCH_FULL, NOW, repay) is not None, "a keeper pushed out may go while a second one stays")
    one_keeper = [c for c in team if c.player_id != "g2"]
    ok(finance.replaced_collateral(one_keeper, new_keeper, "g1", 1.0, t.BENCH_FULL, NOW, repay) is None, "the last goalkeeper cover backs nothing")
    ok(finance.replaced_collateral(one_keeper, new_keeper, "g1", 1.0, t.BENCH_NONE, NOW, repay) is not None, "with no bench wanted it may")
    ok(finance.replaced_collateral(team, replace(star, expires_at=repay), weakest_mid.player_id, 1.0, t.BENCH_FULL, NOW, repay) is None, "too late: nothing")

    ### E04.10: the risk engine rebuilds every claim, E04.06: each sale backs one bid
    ### The starter has no forecast: pessimistic 4 % per update over six days and a buffer, 7.2 of 10 million
    ok(back.value == 7_200_000, f"the pessimistic value of the starter ({back.value:,})")
    listings = {"t": replace(target, price=10_000_000, bid_low=10_000_000), "s": replace(star, value=7_000_000, price=7_000_000, bid_low=7_000_000)}
    bid = A("bid", "lineup", "s", 7_000_000)
    ok(risk.validate([A("bid", "lineup", "s", 7_300_000)], ctx(team, listings, collateral={"s": [back]}, repay_from=repay)) == [risk.OVER_BUDGET],
       "a bid above the pessimistic value is not covered")
    plain = risk.validate([bid], ctx(team, listings))
    ok(plain == [risk.OVER_BUDGET], "without financing: over budget")
    financed = risk.validate([bid], ctx(team, listings, collateral={"s": [back]}, repay_from=repay))
    ok(financed == [None], "financed by the starter pushed out: allowed")
    inflated = replace(back, value=back.value + 1)
    ok(risk.validate([bid], ctx(team, listings, collateral={"s": [inflated]}, repay_from=repay)) == [risk.FINANCE_PLAN_INVALID], "a claim above the rebuilt value is refused")
    ok(risk.validate([bid], ctx(team, listings, collateral={"s": [back]}, repay_from=repay, used_collateral={back.player_id})) == [risk.FINANCE_COLLATERAL_TAKEN],
       "a sale counted for an earlier bid is taken")
    twice = A("bid", "lineup", "s2", 7_000_000)
    listings2 = {**listings, "s2": replace(listings["s"], player_id="s2")}
    claims = {"s": [back], "s2": [replace(back, bid_for="s2")]}
    ok(risk.validate([bid, twice], ctx(team, listings2, collateral=claims, repay_from=repay)) == [None, risk.FINANCE_COLLATERAL_TAKEN],
       "two bids on the same sale: the second is refused")
    ok(risk.validate([bid], ctx(team, listings, collateral={"s": [back]}, repay_from=repay, switches_on=False)) == [risk.KILL_SWITCH], "the switch still wins")

    ### Handover 6.2: balance 0, three profit targets of 10 million rising 5 %, six days to the matchday.
    ### Pessimistic each brings 8.6 million for 10: without credit not even one bid pays itself back
    trio = {f"p{i}": replace(target, player_id=f"p{i}", value=10_000_000, price=10_000_000, bid_low=10_000_000) for i in range(3)}
    trio_claims = {pid: [finance.self_collateral(c, 1.0, NOW, repay)] for pid, c in trio.items()}
    bids = [A("bid", "profit", pid, 10_000_000) for pid in trio]
    no_credit = risk.validate(bids, ctx(team, trio, collateral=trio_claims, repay_from=repay))
    ok(no_credit == [risk.OVER_BUDGET] * 3, f"pessimistic proceeds below the price: no bid without credit ({no_credit})")
    ok(all(c[0].value == 8_600_000 for c in trio_claims.values()), "8.6 million each: 2 % per update over six updates and a buffer")
    shortfall = 30_000_000 - sum(c[0].value for c in trio_claims.values())
    with_credit = risk.validate(bids, ctx(team, trio, collateral=trio_claims, repay_from=repay, credit=shortfall, credit_mode=2))
    ok(with_credit == [None, None, None], f"with credit for the pessimistic shortfall ({shortfall:,}): all three")
    ok(risk.validate(bids, ctx(team, trio, collateral=trio_claims, repay_from=repay, credit=shortfall - 10_000, credit_mode=2))[2] == risk.OVER_BUDGET,
       "one step less: the third is refused")

    print(f"All {passed} trader finance checks passed.")


if __name__ == "__main__":
    main()
