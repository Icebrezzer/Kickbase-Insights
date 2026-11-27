"""P0 safety checks of the autotrader (milestone 1): net profit, bid caps, input validation, credit
collateral, deadline phases, safe sales and the risk engine. Run from backend/:
python tests/check_trader_safety.py"""

from __future__ import annotations

import sys
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import analytics, risk  # noqa: E402
from core import trader as t  # noqa: E402

OPTS = t.Options()
NOW = datetime(2026, 11, 25, 12, tzinfo=UTC)


def p(pid: str, pos: int, expected: float, **kw) -> t.Candidate:
    base = dict(average=expected, form=expected, play=1.0, fit=True, today=0, forecast=0, gain=0, value=5_000_000, team_id=pid)
    return t.Candidate(pid, pos, expected, **{**base, **kw})


def squad() -> list[t.Candidate]:
    players = [p("g1", 1, 50), p("g2", 1, 20)]
    players += [p(f"d{i}", 2, 60 - i * 5) for i in range(5)]
    players += [p(f"m{i}", 3, 70 - i * 5) for i in range(6)]
    players += [p(f"f{i}", 4, 80 - i * 10) for i in range(3)] + [p("f3", 4, 5)]
    best = set(t.best_of(players).player_ids)
    return [replace(c, in_best=c.player_id in best) for c in players]


@dataclass
class A:
    kind: str
    purpose: str
    player_id: str
    price: int


def ctx(**kw) -> risk.Context:
    s = kw.pop("squad", squad())
    listings = kw.pop("listings", {})
    base = dict(
        now=NOW, switches_on=True, deadline=None, budget=20_000_000, reserve=0, credit=0, credit_mode=1, open_bids={},
        trader_bids=set(), squad=s, listings=listings,
        club_of={**{c.player_id: c.team_id for c in s}, **{pid: c.team_id for pid, c in listings.items()}},
        max_squad=25, max_club=3, bids_left=6, sales_left=3, ratio=0.9, min_margin=150_000, min_roi=0.02,
    )
    return risk.Context(**{**base, **kw})


def main() -> None:
    passed = 0

    def ok(condition: bool, label: str) -> None:
        nonlocal passed
        assert condition, label
        passed += 1

    ### 1.1 The order's example: +800k forecast, bid 10.2 Mio., ratio 90 % is a 480k loss, no profit buy
    ex = p("x", 3, 10, value=10_000_000, price=10_000_000, bid_low=10_200_000, bid_high=10_200_000, gain=800_000, forecast=400_000)
    ok(t.expected_profit(ex, 10_200_000, 0.9) == -480_000, "net profit after the instant sale")
    ok(not t.is_profit_buy(ex, 10_200_000, 150_000, 0.9, 0.02), "positive market value gain, negative net: no buy")
    ok(t.max_profit_bid(ex, 0.9, 150_000, 0.02) < 10_200_000, "the economic cap is below the minimum bid")
    ok(risk.validate([A("bid", "profit", "x", 10_200_000)], ctx(listings={"x": replace(ex, expires_at=NOW + timedelta(hours=3))})) == [risk.PROFIT_NEGATIVE],
       "the risk engine refuses it on its own")

    ### Exact minimum margin and return
    m = p("m", 3, 10, value=10_000_000, price=10_000_000, bid_low=10_000_000, gain=2_000_000, forecast=1)
    proceeds = t.expected_proceeds(m, 0.9) # 10.8 Mio.
    ok(t.is_profit_buy(m, proceeds - 150_000, 150_000, 0.9, 0.0), "exactly the minimum margin passes")
    ok(not t.is_profit_buy(m, proceeds - 140_000, 150_000, 0.9, 0.0), "10k short of it does not")
    roi_bid = int(proceeds / 1.02) // 10_000 * 10_000
    ok(t.is_profit_buy(m, roi_bid, 0, 0.9, 0.02) and not t.is_profit_buy(m, roi_bid + 200_000, 0, 0.9, 0.02), "minimum return")
    ok(t.max_profit_bid(m, 0.9, 150_000, 0.02) == 10_580_000, t.max_profit_bid(m, 0.9, 150_000, 0.02))

    ### 1.3 Rounding never goes above a cap, no bid without a valid price
    ok(t.bid_for(m, 1.0, 10_004_999) == 10_000_000, "rounded down to the bid step under the cap")
    ok(t.bid_for(replace(m, value=0, price=0, bid_low=0), 0.5, None) is None, "no price, no bid")
    ok(t.bid_for(m, 0.0, 9_990_000) is None, "minimum above the cap")

    ### 1.4 Ranking by net return per euro: a cheap good return beats an expensive small one
    cheap = p("c", 3, 5, value=2_000_000, gain=600_000)
    dear = p("d", 3, 5, value=20_000_000, gain=2_500_000)
    ok(t.profit_rank(cheap, 2_000_000, 0.9) > t.profit_rank(dear, 20_000_000, 0.9), "return per euro, not absolute gain")

    ### 12.1 Validation: "false" is False, NaN, infinity and junk keep the default
    o = t.Options.load({"shadow": "false", "rescue_override": "true", "min_gain": float("nan"), "reserve": float("inf"),
                        "daily_bids": "1e999", "credit_mode": True, "stop_loss": [1], "min_roi": "-5"})
    ok((o.shadow, o.rescue_override) == (False, True), "booleans parsed, not truthy")
    ok((o.min_gain, o.reserve, o.daily_bids, o.credit_mode, o.stop_loss) == (2.0, 0, 6, 1, 3_000_000), o)
    ok(o.min_roi == 0.0, "clamped to the lower limit")
    ok(t.Options.load({"shadow": "maybe"}).shadow is True, "an unknown boolean keeps the default")
    ok(t.Options.load("garbage") == OPTS, "a broken stored object falls back to the defaults")
    learned = t.Learned.load({"gain_ratio": float("nan"), "min_margin": float("inf"), "extra": [0.2, float("nan"), 0.3], "won": -5})
    ok(learned.gain_ratio == 1.0 and learned.min_margin == t.START_MARGIN and learned.extra == t.Learned().extra and learned.won == 0, learned)

    ### 2.2 Credit collateral: only sellable confirmed players, one by one, never cover or starters
    s = squad()
    bench = [c for c in s if not c.in_best]
    full = t.liquidation_value(s, 0.9, 30)
    ok(full < sum(c.value for c in bench) * 0.9, "the last cover of each position is no collateral")
    ok(t.liquidation_value([replace(c, locked=True) for c in s], 0.9, 30) == 0, "locked players are no collateral")
    ok(t.liquidation_value(s, 0.9, 1) == 4_500_000, "limited by the sales that fit in the time")
    falling = [replace(c, forecast=-1_000_000) if not c.in_best else c for c in s]
    ok(t.liquidation_value(falling, 0.9, 30) < full, "falling values count lower")
    ok(t.credit(5_000_000, 100_000_000, 0) == 0, "no repayable collateral, no credit")

    ### 4.1 Phases, rebuilt from the clock (also after a restart)
    friday = datetime(2026, 11, 27, 19, 30, tzinfo=UTC) # 20:30 in Germany
    ok(t.phase(friday - timedelta(days=3), friday) == "normal", "normal")
    ok(t.phase(friday - timedelta(hours=23), friday) == "prepare", "prepare")
    ok(t.phase(friday - timedelta(hours=20), friday) == "repay", "repay from Thursday 22:15")
    ok(t.phase(friday - timedelta(minutes=30), friday) == "final", "final hour")
    ok(t.phase(friday + timedelta(minutes=1), friday) == "normal", "after the deadline")
    ok(t.phase(NOW, None) == "normal", "no matchday")
    summer = datetime(2027, 3, 26, 19, 30, tzinfo=UTC) # Friday 20:30 CET, two days before summer time
    ok(t.repay_from(summer).astimezone(t.analytics.MARKET_VALUE_TIMEZONE).hour == 22, "22:15 local in winter time")
    after_switch = datetime(2027, 4, 2, 18, 30, tzinfo=UTC) # Friday 20:30 CEST
    ok(t.repay_from(after_switch).astimezone(t.analytics.MARKET_VALUE_TIMEZONE).hour == 22, "and in summer time")

    ### Credit per purpose and phase
    ok(risk.credit_for("profit", None, "normal", None, 5_000_000, 1) == 0, "no credit for profit trades by default")
    ok(risk.credit_for("lineup", None, "normal", None, 5_000_000, 1) == 5_000_000, "credit for the eleven")
    ok(risk.credit_for("lineup", friday - timedelta(hours=2), "repay", friday, 5_000_000, 2) == 0, "no credit ending in the repay window")
    ok(risk.credit_for("lineup", friday + timedelta(hours=2), "repay", friday, 5_000_000, 2) == 5_000_000, "after the deadline it may")
    ok(risk.credit_for("lineup", None, "final", friday, 5_000_000, 2) == 0, "never in the last hour")
    ok(risk.credit_for("lineup", None, "normal", None, 5_000_000, 0) == 0, "mode 0: never")

    ### 3.2 Room sales: the confirmed squad only, never a starter, never the last cover, never a new gap
    target = p("x", 3, 90, forecast=900_000, today=100_000)
    sale = t.pick_sale(s, target, 0.6, 50_000)
    ok(sale is not None and not sale.in_best and t.keeps_cover(s, sale), sale)
    starters_only = [c for c in s if c.in_best] + [p("g2", 1, 20), p("dx", 2, 1), p("mx", 3, 1), p("fx", 4, 1)]
    starters_only = [replace(c, in_best=c.player_id in set(t.best_of(starters_only).player_ids)) for c in starters_only]
    ok(t.pick_sale(starters_only, target, 0.6, 0) is None, "one cover per position and a starter: nothing to give up")
    rare_starter = [replace(c, play=0.2) if c.in_best and c.position == 4 else c for c in s]
    pick = t.pick_sale(rare_starter, target, 0.6, 10**9)
    ok(pick is None or not (pick.fit and pick.in_best), "a fit starter is never sold for room, even a non-regular")

    ### 10 Risk engine: worst case with every open bid won, limits, manual bids, kill switch
    x = p("x", 3, 30, value=5_000_000, price=5_000_000, bid_low=5_000_000, team_id="t9", expires_at=NOW + timedelta(hours=5))
    y = replace(x, player_id="y")
    listings = {"x": x, "y": y}
    ok(risk.validate([A("bid", "lineup", "x", 5_000_000)], ctx(listings=listings, budget=9_000_000, open_bids={"o": 5_000_000})) == [risk.OVER_BUDGET],
       "open (also manual) bids count as spent")
    ok(risk.validate([A("bid", "lineup", "x", 5_000_000)], ctx(listings=listings, budget=9_000_000, open_bids={"o": 5_000_000}, credit=1_000_000)) == [None],
       "unless covered credit allows it")
    two = [A("bid", "lineup", "x", 5_000_000), A("bid", "lineup", "y", 5_000_000)]
    ok(risk.validate(two, ctx(listings=listings, budget=8_000_000)) == [None, risk.OVER_BUDGET], "the plan as a whole, both won")
    ok(risk.validate(two, ctx(listings=listings, max_squad=len(s) + 1)) == [None, risk.SQUAD_FULL], "squad limit with every bid")
    ok(risk.validate(two, ctx(listings=listings, max_club=1, club_of={"x": "t9", "y": "t9"})) == [None, risk.CLUB_FULL], "club limit with every bid")
    ok(risk.validate(two, ctx(listings=listings, bids_left=1)) == [None, risk.DAILY_BIDS], "daily bids")
    ok(risk.validate(two, ctx(listings=listings, switches_on=False)) == [risk.KILL_SWITCH] * 2, "kill switch")
    ok(risk.validate([A("bid", "lineup", "x", 5_005_000)], ctx(listings=listings)) == [risk.BID_INVALID], "off the bid step")
    ok(risk.validate([A("bid", "lineup", "x", 5_000_000)], ctx(listings={"x": replace(x, expires_at=NOW)})) == [risk.AUCTION_EXPIRED], "expired")
    ok(risk.validate([A("bid", "profit", "x", 5_000_000)], ctx(listings={"x": replace(x, expires_at=None)})) == [risk.AUCTION_UNKNOWN], "no end, no profit bid")
    ok(risk.validate([A("bid", "lineup", "x", 5_000_000)], ctx(listings=listings, blocked={"x"})) == [risk.BLOCKED], "rebuy block / unsettled call")
    ok(risk.validate([A("bid", "lineup", "x", 5_000_000)], ctx(listings=listings, reserve=16_000_000)) == [risk.OVER_BUDGET], "reserve")
    deadline = NOW + timedelta(minutes=30)
    ok(risk.validate([A("bid", "profit", "x", 5_000_000)], ctx(listings=listings, deadline=deadline)) == [risk.PHASE], "no profit bids in the last hour")
    ok(risk.validate([A("withdraw", "lineup", "o", 1)], ctx(open_bids={"o": 1})) == [risk.MANUAL_BID], "manual bids are never withdrawn")
    ok(risk.validate([A("withdraw", "lineup", "o", 1)], ctx(open_bids={"o": 1}, trader_bids={"o"})) == [None], "the trader's own may be")

    starter = next(c for c in s if c.in_best and c.position == 3)
    keeper2 = next(c for c in s if c.player_id == "g2")
    spare = next(c for c in s if not c.in_best and c.position == 3)
    ok(risk.validate([A("sell", "room", starter.player_id, 1)], ctx()) == [risk.STARTER], "starter")
    ok(risk.validate([A("sell", "room", keeper2.player_id, 1)], ctx()) == [risk.BREAKS_COVER], "only fit substitute keeper")
    ok(risk.validate([A("sell", "room", "nobody", 1)], ctx()) == [risk.NOT_OWNED], "not owned")
    locked = [replace(c, locked=True) if c is spare else c for c in s]
    ok(risk.validate([A("sell", "room", spare.player_id, 1)], ctx(squad=locked)) == [risk.LOCKED], "locked")
    ok(risk.validate([A("sell", "rescue", spare.player_id, 1)], ctx(squad=locked)) == [risk.LOCKED], "rescue keeps locks by default")
    ok(risk.validate([A("sell", "rescue", spare.player_id, 1)], ctx(squad=locked, rescue_override=True)) == [None], "unless the user allowed it")
    ok(risk.validate([A("sell", "room", spare.player_id, 1)] * 2, ctx(sales_left=1)) == [None, risk.NOT_OWNED], "sold once")
    ok(risk.validate([A("sell", "room", spare.player_id, 1)], ctx(sales_left=0)) == [risk.DAILY_SALES], "daily sales")

    ### Own offers on the market: "uoid"/"uop" read as offer id and price, the old reading as user id still
    ### seen as a bid (but without an id to withdraw it), "ofs" first
    from kickbase.models import MarketPlayer

    item = MarketPlayer.model_validate
    ### A real market entry with an open bid (25.11.2026): no offer id, uoid is the bidder's user id
    real = item({"i": "13888", "ofc": 1, "exs": 8679, "prc": 6468331, "uop": 6480000, "uoid": "4067677",
                 "ofs": [{"u": "4067677", "unm": "Nicolinho", "uoid": "4067677", "uop": 6480000, "st": 0}], "mv": 6468331})
    ok(real.own_bid("4067677") == 6_480_000, "own bid from ofs")
    ok(real.own_offer_id("4067677") == "4067677", "withdrawn by the user's id, the offer has none of its own")
    ok(real.own_bid("999") is None and real.own_offer_id("999") is None, "another viewer sees no own offer")
    ok(item({"i": "7", "uoid": "1001", "uop": 1_500_000}).own_offer_id("1001") == "1001", "the item's pair as fallback")
    ok(item({"i": "7", "ofs": [{"i": "o5", "u": "1001", "uop": 900_000}]}).own_offer_id("1001") == "o5", "an explicit id wins")
    ok(item({"i": "13888", "ofc": 0, "prc": 6_468_331}).own_bid("4067677") is None, "no offer (ofc 0)")

    ### Invariant over many plans: approved bids never exceed balance + allowed credit with every bid won
    import random

    rng = random.Random(7)
    for _ in range(300):
        budget = rng.randrange(-5_000_000, 30_000_000, 10_000)
        credit = rng.randrange(0, 10_000_000, 10_000)
        open_bids = {f"o{i}": rng.randrange(1_000_000, 8_000_000, 10_000) for i in range(rng.randrange(0, 3))}
        market = {f"x{i}": replace(x, player_id=f"x{i}", team_id=f"t{rng.randrange(3)}", value=v, price=v, bid_low=v)
                  for i, v in enumerate(rng.randrange(1_000_000, 12_000_000, 10_000) for _ in range(6))}
        plan = [A("bid", rng.choice(["lineup", "cover"]), pid, c.value + rng.randrange(0, 2_000_000, 10_000)) for pid, c in market.items()]
        c = ctx(listings=market, budget=budget, credit=credit, open_bids=open_bids, club_of={pid: m.team_id for pid, m in market.items()},
                max_squad=len(s) + rng.randrange(0, 6), max_club=2, reserve=rng.randrange(0, 3_000_000, 10_000))
        codes = risk.validate(plan, c)
        approved = [a for a, code in zip(plan, codes, strict=True) if code is None]
        ok(not approved or budget - sum(open_bids.values()) - sum(a.price for a in approved) >= c.reserve - credit, "money invariant")
        ok(len(approved) <= max(c.max_squad - len(s) - len(open_bids), 0), "squad invariant")
        ok(max([sum(1 for a in approved if market[a.player_id].team_id == team) for team in ("t0", "t1", "t2")]) <= 2, "club invariant")

    ### E01.04: max bid next to the released money; the named limits add up to the difference exactly
    def money(budget, team_value, open_bids, reserve, liquidation, mode, stage="normal", room=10**12):
        loan = t.credit(budget, team_value, liquidation)
        purposes = ("lineup", "cover", "profit")
        return t.money_check(
            budget, team_value, open_bids, reserve, loan,
            {pp: risk.credit_for(pp, None, stage, None, loan, mode) for pp in purposes},
            {pp: risk.credit_for(pp, None, "normal", None, loan, mode) for pp in purposes}, room,
        )

    ### The league without buys (E01.01): balance 0.46 Mio., reserve 2 Mio., credit mode 1
    m = money(460_000, 254_250_000, 0, 2_000_000, 12_940_000, 1)
    ok(m["max_bid"] == analytics.max_bid(460_000, 254_250_000), "max bid as Kickbase computes it")
    ok(m["released"]["profit"] == 460_000 - 2_000_000 < 0, f"credit mode 1: profit trades get the cash alone ({m['released']['profit']})")
    ok(m["released"]["lineup"] == 460_000 - 2_000_000 + 12_940_000, "credit mode 1: the eleven gets the credit")
    ok(m["limits"]["profit"].get(t.LIMIT_CREDIT_MODE) == 12_940_000, "the credit mode is named as the profit limit")
    ok(t.LIMIT_CREDIT_MODE not in m["limits"]["lineup"], "no credit mode limit for the eleven")
    ok(m["limits"]["lineup"][t.LIMIT_RESERVE] == 2_000_000 and m["limits"]["lineup"][t.LIMIT_LIQUIDATION] > 0, "reserve and liquidation named")
    ### Close to the deadline it is the phase, not the mode
    m = money(5_000_000, 100_000_000, 0, 0, 20_000_000, 2, stage="final")
    ok(m["released"]["lineup"] == 5_000_000 and m["limits"]["lineup"].get(t.LIMIT_PHASE) == 20_000_000, "final phase: the phase limits")
    ### Negative balance and open bids above the balance
    m = money(-3_000_000, 60_000_000, 0, 0, 30_000_000, 1)
    ok(m["limits"]["lineup"].get(t.LIMIT_DEBT) == 3_000_000, "a negative balance is named as debt")
    m = money(2_000_000, 60_000_000, 5_000_000, 0, 30_000_000, 1)
    ok(m["max_bid_free"] == m["max_bid"] - 5_000_000 and m["released"]["profit"] == -3_000_000, "open bids above the balance")
    m = money(10_000_000, 60_000_000, 0, 0, 30_000_000, 2, room=4_000_000)
    ok(m["released"]["profit"] == 4_000_000 and m["limits"]["profit"][t.LIMIT_PROFIT_ROOM] > 0, "profit room caps profit trades")
    rng = random.Random(11)
    for _ in range(500):
        args = (rng.randrange(-20_000_000, 40_000_000, 10_000), rng.randrange(0, 300_000_000, 10_000), rng.randrange(0, 30_000_000, 10_000),
                rng.randrange(0, 5_000_000, 10_000), rng.randrange(0, 80_000_000, 10_000), rng.randrange(0, 3))
        m = money(*args, stage=rng.choice(["normal", "prepare", "repay", "final"]), room=rng.randrange(-5_000_000, 50_000_000, 10_000))
        ok(all(m["gap"][pp] == sum(m["limits"][pp].values()) for pp in m["released"]), f"limits add up to the gap {args}")

    ### Instant sale ratio per league: Kickbase pays the market value. Default unchanged, a learned one only lowers
    ok(t.Options().sell_ratio == 90 and t.Options.load({"sell_ratio": 130}).sell_ratio == 100, "sell ratio default 90, at most 100")
    ok(t.Options.load({"sell_ratio": 10}).sell_ratio == 50 and t.Options.load({"sell_ratio": "x"}).sell_ratio == 90, "sell ratio clamped")
    full = t.Options.load({"sell_ratio": 100})
    ok(t.sell_ratio(full, None) == 1.0 and t.sell_ratio(full, 0.97) == 0.97 and t.sell_ratio(full, 1.2) == 1.0, "learned ratio only lowers")
    ok(t.sell_ratio(t.Options(), None) == 0.9, "default ratio as before")
    ok(all(t.profile(name).sell_ratio == 90 for name in t.PROFILES), "profiles leave the sell ratio")
    ### The E01.01 case: +6 % in two updates at a bid 0.2 % above the value loses at 90 %, earns at 100 %
    riser = p("r", 3, 50, value=10_000_000, price=10_000_000, bid_low=10_020_000, forecast=300_000, gain=600_000)
    ok(not t.is_profit_buy(riser, 10_020_000, 150_000, 0.9, 0.03), "at 90 % no profit buy")
    ok(t.is_profit_buy(riser, 10_020_000, 150_000, 1.0, 0.03), "at 100 % a profit buy")

    ### E05.08: a target that changes the formation (3-5-2 -> 4-5-1) and pushes out a forward with a high
    ### season average but few expected points now
    eleven = [p("g", 1, 50), *(p(f"d{i}", 2, 60 - i * 5) for i in range(3)), *(p(f"m{i}", 3, 70 - i * 5) for i in range(5)),
              p("f0", 4, 80), p("f1", 4, 40, average=150, form=150, ahead=30)]
    target = p("x", 2, 90, average=90, form=90, ahead=85)
    off, on = t.Options(), t.Options(upgrade_cross_position=True)
    ok(t.lineup_upgrade(eleven, target, off) is None, "flag off: judged by the forward's season quality, as before")
    up = t.lineup_upgrade(eleven, target, on)
    ok(up is not None and up.replaced == "f1" and up.gain >= on.min_gain, f"flag on: the points decide ({up})")
    one_off = replace(target, ahead=20)
    ok(t.lineup_upgrade(eleven, one_off, on) is None, "flag on: worse over the next three matches is still no upgrade")
    ok(t.lineup_upgrade(eleven, replace(target, average=None, form=None), on) is None, "flag on: no quality data is still no upgrade")
    ### Same position: the quality rule stays, flag or not
    strong_front = [*eleven[:-1], p("f1", 4, 75, ahead=75)]
    weak_back = p("y", 2, 58, average=10, form=10, ahead=85)
    ok(t.best_of([*strong_front, weak_back]).formation == t.best_of(strong_front).formation, "same formation for the next check")
    ok(t.lineup_upgrade(strong_front, weak_back, on) is None, "same position: quality still counts")
    ok(t.lineup_upgrade(strong_front, replace(weak_back, average=58, form=58), on) is not None, "same position: a better one is an upgrade")
    ok(t.Options.load({"upgrade_cross_position": "true"}).upgrade_cross_position is True, "the flag loads from JSON")

    print(f"All {passed} trader safety checks passed.")


if __name__ == "__main__":
    main()
