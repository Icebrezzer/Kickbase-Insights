"""Pure shadow analysis primitives (E03.03/E03.04).

No database, network, live trading or learning state. Callers must supply
observations from one user/league and verified auction outcomes.
"""
from __future__ import annotations

from collections import Counter, defaultdict, deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum


@dataclass(frozen=True)
class Candidate:
    player_id: str
    auction: str
    price_class: int
    reason: str

    @property
    def key(self) -> tuple[str, str]:
        return self.player_id, self.auction

    @property
    def stratum(self) -> tuple[int, str]:
        return self.price_class, self.reason


def select_candidates(
    candidates: Iterable[Candidate],
    existing: set[tuple[str, str]],
    counts: Mapping[tuple[int, str], int],
    limit: int,
) -> list[Candidate]:
    """Prefer underrepresented strata, then round-robin within them.

    Existing snapshots do not consume the new-row budget. Counts must be
    scoped to the same user/league and updated after successful persistence.
    Ties are deterministic; no guarantee of coverage if candidates disappear.
    """
    if limit < 0:
        raise ValueError("negative snapshot limit")
    groups: dict[tuple[int, str], deque[Candidate]] = defaultdict(deque)
    seen = set(existing)
    for candidate in sorted(candidates, key=lambda c: (c.key, c.stratum)):
        if candidate.key not in seen:
            groups[candidate.stratum].append(candidate)
            seen.add(candidate.key)
    weights = Counter(counts)
    result: list[Candidate] = []
    while groups and len(result) < limit:
        stratum = min(groups, key=lambda s: (weights[s], s))
        result.append(groups[stratum].popleft())
        weights[stratum] += 1
        if not groups[stratum]:
            del groups[stratum]
    return result


class AuctionOutcome(StrEnum):
    WON = "won"
    LOST = "lost"
    UNKNOWN = "unknown"
    NO_BUYER = "no_buyer"


@dataclass(frozen=True)
class AuctionEvidence:
    """Evidence must belong to the exact auction, not merely the player."""
    winner_price: int | None = None
    confirmed_no_buyer: bool = False

    def __post_init__(self) -> None:
        if self.winner_price is not None and self.winner_price <= 0:
            raise ValueError("invalid winner price")
        if self.confirmed_no_buyer and self.winner_price is not None:
            raise ValueError("contradictory auction evidence")


@dataclass(frozen=True)
class BidVariant:
    name: str
    amount: int
    outcome: AuctionOutcome


def bid_variants(
    minimum: int,
    standard: int | None,
    ceiling: int | None,
    *,
    step: int = 10_000,
) -> dict[str, int]:
    """Build ex-ante bids; ceiling is a hypothetical economic bound.

    No claim of live financeability. EV-optimal is deliberately omitted
    until a full probability curve and payoff model are available.
    """
    if step <= 0 or minimum <= 0:
        raise ValueError("invalid bid step or minimum")
    floor = ((minimum + step - 1) // step) * step
    cap = (ceiling // step) * step if ceiling is not None else None
    if cap is not None and cap < floor:
        return {}
    def bounded(value: int) -> int:
        rounded = max(floor, ((value + step - 1) // step) * step)
        return min(rounded, cap) if cap is not None else rounded
    base = bounded(standard if standard is not None else floor)
    return {"minimum": floor, "defensive": bounded(base - step),
            "standard": base, "aggressive": bounded(base + step)}


def settle_bids(variants: Mapping[str, int], evidence: AuctionEvidence) -> tuple[BidVariant, ...]:
    """Conditional on unchanged rival bids. All variants share one sample."""
    result = []
    for name, amount in variants.items():
        if amount <= 0:
            raise ValueError("invalid hypothetical bid")
        price = evidence.winner_price
        if evidence.confirmed_no_buyer:
            outcome = AuctionOutcome.NO_BUYER
        elif price is None or amount == price:
            outcome = AuctionOutcome.UNKNOWN
        elif amount > price:
            outcome = AuctionOutcome.WON
        else:
            outcome = AuctionOutcome.LOST
        result.append(BidVariant(name, amount, outcome))
    return tuple(result)


def sale_strategies(start: int, points: Mapping[int, tuple[int, int | None]], ratio: float,
                    trailing: int, deadline: int | None) -> dict:
    """Replay at most 14 consecutive market updates. Never fill missing prices or forecasts."""
    exits = {}
    peak = 0
    forecast_known = True
    if not 0 < ratio <= 1:
        return {}
    for day in range(start, start + 15):
        point = points.get(day)
        if point is None or point[0] <= 0:
            break
        value, forecast = point
        peak = max(peak, value)
        update = day - start
        proceeds = int(value * ratio)
        if update in (1, 2, 3):
            exits[f"hold_{update}"] = proceeds
        if day == deadline:
            exits["deadline"] = proceeds
        if update:
            forecast_known = forecast_known and forecast is not None
            if forecast_known and forecast <= 0:
                exits.setdefault("forecast", proceeds)
            if trailing and value * 100 <= peak * (100 - trailing):
                exits.setdefault("trailing", proceeds)
    return {"exits": exits, "diagnostic_peak": peak or None}


def classify(reason: str, inputs: dict, result: dict) -> tuple[str, int | None, str]:
    """One canonical alternative per auction: standard bid and two market updates."""
    bid = inputs.get("bids", {}).get("standard")
    outcome = result.get("outcomes", {}).get("standard")
    cap = inputs.get("cap")
    finance = "unknown" if bid is None or cap is None else "feasible" if bid <= cap else "infeasible"
    if result.get("own"):
        return "purchased", None, finance
    if outcome in ("lost", "no_buyer"):
        return outcome, None, finance
    proceeds = result.get("exits", {}).get("hold_2")
    if outcome != "won" or bid is None or proceeds is None:
        return "unknown", None, finance
    net = proceeds - bid
    if reason == "BID_PLANNED" or net == 0:
        return "hypothetical", net, finance
    return ("missed" if net > 0 else "avoided"), net, finance
