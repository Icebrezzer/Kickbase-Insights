"""Financing of the autotrader (E04): what selling players brings in different scenarios, and which
open bid may count on which future sale. Pure functions; the planning (sync/trader.py) and the risk
engine (core/risk.py) both use them, so the risk engine checks a financing plan on its own.

Scenarios of a sale value (E04.03):
- optimistic: the forecast as it is,
- realistic: the forecast scaled by the learned confidence,
- pessimistic: the forecast falls short by STRESS_RISING (rising forecast) or STRESS_FALLING (falling or no
  forecast) of the value per market value update until the sale, plus one update of buffer (a sale that
  slips past an update, e.g. while Kickbase is down). Starting values from the real exports
  (docs/autotrader/MASTERPLAN.md 9.2), to be calibrated with the forecast quality of E10.00.

Credit is only released on the pessimistic scenario. A conditional collateral (E04.04, E04.05) is a sale
that only becomes possible when the bid is won: the target itself after its holding time (profit), or
the starter it pushes out of the eleven (lineup). Each player backs at most one bid (S2).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from core import analytics
from core import trader as t

### Pessimistic shortfall per market value update, as a share of the value
STRESS_RISING = 0.02
STRESS_FALLING = 0.04
### Updates of buffer a sale may slip
BUFFER_UPDATES = 1
### A conditional sale must be possible this long before the repay phase starts (Kickbase down, retries)
SAFETY_MARGIN = timedelta(hours=6)

SCENARIOS = ("optimistic", "realistic", "pessimistic")


def updates_between(start: datetime, end: datetime) -> int:
    """Market value updates (22:00 Berlin) after `start` up to `end`."""
    return max(analytics.market_value_day(end) - analytics.market_value_day(start), 0)


def sale_value(c: t.Candidate, ratio: float, scenario: str, updates: int = 0, confidence: float = 1.0) -> int:
    """What selling `c` brings after `updates` market value updates, in a scenario. The forecast of the
    next update (`c.forecast`) is spread over the updates; never below zero. "current" is the valuation of
    2.0 (core.trader.liquidation_value): the value after a falling forecast, no stress."""
    if scenario == "current":
        value = c.value + min(c.forecast, 0)
    elif scenario == "optimistic":
        value = c.value + c.forecast * max(updates, 1)
    elif scenario == "realistic":
        value = c.value + c.forecast * max(updates, 1) * confidence
    else:
        stress = STRESS_RISING if c.forecast > 0 else STRESS_FALLING
        value = (c.value + min(c.forecast, 0)) * (1 - stress * (updates + BUFFER_UPDATES))
    return int(max(value, 0) * ratio)


def liquidation(squad: Sequence[t.Candidate], ratio: float, max_sales: int, bench: int, scenario: str,
                updates: int = 0, confidence: float = 1.0) -> int:
    """The liquidation of core.trader.liquidation_value (same players, same order, same limits), each sale
    valued in a scenario."""
    remaining = list(squad)
    total = sales = 0
    for p in t.sell_order(squad, 1.0):
        if sales >= max_sales:
            break
        if p.locked or p.in_best or not t.keeps_cover(remaining, p, bench):
            continue
        total += sale_value(p, ratio, scenario, updates, confidence)
        remaining.remove(p)
        sales += 1
    return total


@dataclass(frozen=True)
class Collateral:
    """A sale that pays back the bid on `bid_for` once it is won."""
    bid_for: str # The player bid on
    player_id: str # The player sold: the target itself (profit) or the starter pushed out (lineup)
    kind: str # "self" (E04.04) or "replaced" (E04.05)
    value: int # Pessimistic proceeds
    sell_from: datetime # Earliest sale
    sell_until: datetime # Latest sale: the start of the repay phase


def self_collateral(target: t.Candidate, ratio: float, now: datetime, repay_from: datetime | None) -> Collateral | None:
    """E04.04: a profit target pays back its own bid. It can be sold after the auction ends and the holding
    time of own buys is over; that has to be well before the repay phase."""
    if repay_from is None or target.expires_at is None or not target.fit or target.forecast <= 0:
        return None
    sell_from = target.expires_at + t.MIN_HOLD
    if sell_from + SAFETY_MARGIN > repay_from:
        return None
    value = sale_value(target, ratio, "pessimistic", updates_between(now, repay_from))
    return Collateral(target.player_id, target.player_id, "self", value, sell_from, repay_from) if value > 0 else None


def replaced_collateral(own: Sequence[t.Candidate], target: t.Candidate, replaced_id: str | None, ratio: float, bench: int,
                        now: datetime, repay_from: datetime | None) -> Collateral | None:
    """E04.05: the starter the target pushes out pays back a lineup bid. Only a player who may be sold once
    the target is there: not locked, and his sale leaves the cover and the eleven as they are with the
    target. Until the auction is won he stays a starter and stays protected."""
    if repay_from is None or target.expires_at is None or replaced_id is None:
        return None
    replaced = next((p for p in own if p.player_id == replaced_id), None)
    if replaced is None or replaced.locked:
        return None
    if target.expires_at + SAFETY_MARGIN > repay_from:
        return None
    with_target = [*own, target]
    without = [p for p in with_target if p.player_id != replaced_id]
    if not t.keeps_cover(with_target, replaced, bench) or t.best_of(without).empty_slots > t.best_of(with_target).empty_slots:
        return None
    value = sale_value(replaced, ratio, "pessimistic", updates_between(now, repay_from))
    return Collateral(target.player_id, replaced_id, "replaced", value, target.expires_at, repay_from) if value > 0 else None


def check_collateral(c: Collateral, own: Sequence[t.Candidate], target: t.Candidate | None, ratio: float, bench: int,
                     now: datetime, repay_from: datetime | None) -> str | None:
    """The risk engine's own check of a claimed collateral (E04.10): rebuilt from the confirmed squad and
    the listing, it must exist and be worth at least what the plan counts on. None when it holds."""
    if target is None or target.player_id != c.bid_for:
        return "FINANCE_PLAN_INVALID"
    if c.kind == "self":
        again = self_collateral(target, ratio, now, repay_from)
    elif c.kind == "replaced":
        again = replaced_collateral(own, target, c.player_id, ratio, bench, now, repay_from)
    else:
        return "FINANCE_PLAN_INVALID"
    if again is None or again.player_id != c.player_id or again.value < c.value:
        return "FINANCE_PLAN_INVALID"
    return None
