"""What the app learns from its own data. Pure functions, the storage is in `sync/learning.py`.

- Expected points: the weights of form, season average, odds and table are fitted to the real points.
- Bidders: who won which auction, against the features every manager had when it was listed.
- Achievements: whether Kickbase pays the player achievements once per matchday or per player,
  decided from how its own counters move.
- Instant sales: what Kickbase pays against the market value.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from statistics import median

from core import coach
from core.analytics import least_squares

### ===============================================================================
### Expected points
### ===============================================================================

MIN_EXPECTATION_ROWS = 300


@dataclass(frozen=True)
class ExpectationRow:
    """One player on one matchday: what was known before, and what he scored."""
    form: float | None
    average: float | None
    chance: float # Chance to play times availability
    win: float | None # Win probability of his club, when odds were known
    table: float # table_term of the opponent, used when there were no odds
    home: bool | None
    actual: int


def _base(row: ExpectationRow, form_w: float, average_w: float) -> float:
    if row.form is not None and row.average is not None:
        return form_w * row.form + average_w * row.average
    value = row.form if row.form is not None else row.average
    return (value or 0.0) * (form_w + average_w)


def predict(row: ExpectationRow, w: coach.ExpectationWeights) -> float:
    base = _base(row, w.form, w.average)
    low, high = coach.FACTOR_RANGE
    if row.win is not None:
        factor = 1 + w.win * (row.win - coach.TYPICAL_WIN)
    else:
        factor = 1 + w.table * row.table + (coach.HOME_BONUS if row.home else -coach.HOME_BONUS if row.home is False else 0)
    return max(base, 0.0) * row.chance * max(low, min(high, factor))


def fit_expectation(rows: Sequence[ExpectationRow]) -> coach.ExpectationWeights:
    """Least squares on the linearised model

        actual ~ a * chance * form + b * chance * average + c * chance * base * (win - 0.4)
                 + d * chance * base * table

    `base` uses the starting weights, so c and d come out as slopes relative to it.
    """
    default = coach.ExpectationWeights()
    usable = [r for r in rows if r.form is not None and r.average is not None]
    if len(usable) < MIN_EXPECTATION_ROWS:
        return default
    features, targets = [], []
    for r in usable:
        base = _base(r, default.form, default.average)
        win_term = (r.win - coach.TYPICAL_WIN) if r.win is not None else 0.0
        table = r.table if r.win is None else 0.0
        features.append([r.chance * (r.form or 0), r.chance * (r.average or 0), r.chance * base * win_term, r.chance * base * table])
        targets.append(r.actual)
    ### A column without any data (no odds yet, or only odds) cannot be fitted: it keeps its starting value
    defaults = [default.form, default.average, default.win * (default.form + default.average), default.table * (default.form + default.average)]
    active = [i for i in range(4) if any(row[i] for row in features)]
    solution = least_squares([[row[i] for i in active] for row in features], targets) if active else None
    if solution is None:
        return default
    coefficients = list(defaults)
    for index, value in zip(active, solution, strict=True):
        coefficients[index] = value
    a, b, c, d = coefficients
    scale = max(a + b, 0.1)
    fitted = coach.ExpectationWeights(
        form=round(min(max(a, 0.0), 1.5), 3),
        average=round(min(max(b, 0.0), 1.5), 3),
        win=round(min(max(c / scale, 0.0), 1.0), 3) if 2 in active else default.win,
        table=round(min(max(d / scale, 0.0), 0.4), 3) if 3 in active else default.table,
        rows=len(usable),
    )
    error = sum(abs(predict(r, fitted) - r.actual) for r in usable) / len(usable)
    default_error = sum(abs(predict(r, default) - r.actual) for r in usable) / len(usable)
    ### Only take the new weights when they really are better
    if error >= default_error:
        return coach.ExpectationWeights(rows=0, error=default_error, default_error=default_error)
    return coach.ExpectationWeights(
        fitted.form, fitted.average, fitted.win, fitted.table, fitted.rows, round(error, 1), round(default_error, 1)
    )


def history_rows(
    matches: Sequence[Sequence], opponents: dict[int, tuple[str | None, bool]], placements: dict[str, int | None]
) -> list[ExpectationRow]:
    """Rows rebuilt from a player's past matches: for every match, what his earlier ones said.

    `matches` are the stored form rows `[matchday, points, minutes, role, ...]` in any order,
    `opponents` maps a matchday to the opponent and whether it was at home. Status and odds of the
    past are unknown: the player counts as available, the table stands in for the odds.
    """
    ordered = sorted((m for m in matches if m and m[0] is not None), key=lambda m: m[0])
    teams = max((v for v in placements.values() if v is not None), default=18)
    rows = []
    for index in range(3, len(ordered)):
        before = [coach.MatchForm(int(m[1]), int(m[2] or 0) if len(m) > 2 else 0, m[3] if len(m) > 3 else None) for m in ordered[:index]]
        recent = list(reversed(before))[:5]
        played_points = [m.points for m in before if m.played]
        if not played_points:
            continue
        form = coach.form_points([m.points for m in recent if m.played])
        chance = coach.play_probability(recent) or 0.0
        day = int(ordered[index][0])
        opponent, home = opponents.get(day, (None, None))
        rows.append(
            ExpectationRow(
                form=form,
                average=sum(played_points) / len(played_points),
                chance=chance,
                win=None,
                table=coach.table_term(placements.get(opponent or ""), max(teams, 2)),
                home=home,
                actual=int(ordered[index][1] or 0),
            )
        )
    return rows


### ===============================================================================
### Bidders
### ===============================================================================

BIDDER_FEATURES = ("need", "interest", "activity", "squad_full")
MIN_AUCTIONS = 50


@dataclass(frozen=True)
class BidderModel:
    """Logistic weights for "this manager wins the auction", learned from the logged auctions."""
    weights: tuple[float, ...] = ()
    bias: float = 0.0
    auctions: int = 0

    @property
    def learned(self) -> bool:
        return bool(self.weights)

    def probability(self, features: Sequence[float]) -> float:
        z = self.bias + sum(w * x for w, x in zip(self.weights, features, strict=True))
        return 1 / (1 + math.exp(-max(-30.0, min(30.0, z))))


def fit_bidders(samples: Sequence[tuple[Sequence[float], int]], auctions: int, steps: int = 800, rate: float = 0.5) -> BidderModel:
    """Logistic regression by gradient descent: features of every candidate, 1 for the winner."""
    if auctions < MIN_AUCTIONS or not samples:
        return BidderModel(auctions=auctions)
    size = len(samples[0][0])
    weights = [0.0] * size
    bias = 0.0
    n = len(samples)
    for _ in range(steps):
        grad_w = [0.0] * size
        grad_b = 0.0
        for features, label in samples:
            z = bias + sum(w * x for w, x in zip(weights, features, strict=True))
            error = 1 / (1 + math.exp(-max(-30.0, min(30.0, z)))) - label
            grad_b += error
            for i, x in enumerate(features):
                grad_w[i] += error * x
        bias -= rate * grad_b / n
        weights = [w - rate * g / n for w, g in zip(weights, grad_w, strict=True)]
    return BidderModel(tuple(round(w, 3) for w in weights), round(bias, 3), auctions)


### ===============================================================================
### Achievements
### ===============================================================================

PLAYER_RULES = ("player_200", "player_300", "player_400", "player_500")


def parse_achievement_counts(raw: object) -> dict[str, int]:
    """Name -> counter from Kickbase's undocumented achievements answer. The usual keys are tried."""
    found: dict[str, int] = {}

    def walk(node: object, depth: int = 0) -> None:
        if depth > 6:
            return
        if isinstance(node, dict):
            name = next((node[k] for k in ("n", "ti", "name", "t", "title") if isinstance(node.get(k), str)), None)
            count = next(
                (node[k] for k in ("c", "cnt", "count", "ac", "am", "a", "nr") if isinstance(node.get(k), int) and not isinstance(node.get(k), bool)),
                None,
            )
            if name and count is not None:
                found[name.strip()] = count
            for value in node.values():
                walk(value, depth + 1)
        elif isinstance(node, list):
            for value in node:
                walk(value, depth + 1)

    walk(raw)
    return found


def rule_for(name: str) -> str | None:
    """The rule key of an achievement name Kickbase shows, matched on the rule's name."""
    from core.achievements import RULES

    lowered = name.casefold()
    for rule in sorted(RULES, key=lambda r: -len(r.name)):
        if rule.name.casefold() in lowered:
            return rule.key
    return None


def mode_votes(
    kickbase_delta: dict[str, int], per_matchday: dict[str, int], per_player: dict[str, int]
) -> tuple[int, int]:
    """Compares how Kickbase's counters moved over some matchdays with both ways of counting.
    Returns (votes for once per matchday, votes for once per player)."""
    matchday_votes = player_votes = 0
    for key in PLAYER_RULES:
        if key not in kickbase_delta:
            continue
        delta = kickbase_delta[key]
        if per_matchday.get(key) == per_player.get(key):
            continue # Both say the same, no evidence
        if delta == per_matchday.get(key):
            matchday_votes += 1
        elif delta == per_player.get(key):
            player_votes += 1
    return matchday_votes, player_votes


### ===============================================================================
### Instant sales and lost auctions
### ===============================================================================


def sell_ratio(observations: Iterable[tuple[int, int]]) -> float | None:
    """Median of received / market value of the instant sales."""
    ratios = [received / value for received, value in observations if value > 0 and received > 0]
    return round(median(ratios), 4) if ratios else None


def lost_gaps(lost: Iterable[tuple[int, int, int]]) -> dict[int, float]:
    """Per price class the median of what winners paid above the lost own bid.
    `lost` holds (market value or own bid, own bid, winner's price)."""
    by_class: dict[int, list[float]] = {}
    for value, own, price in lost:
        if own > 0 and price > own:
            by_class.setdefault(coach.price_class(value), []).append(price / own - 1)
    return {c: round(median(v), 4) for c, v in by_class.items()}
