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
### Held-out rows needed before the weights are judged on them instead of on the training rows
HOLDOUT_MIN = 60


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
    ### Judged on rows the fit did not see: every fifth row is held out (with enough of them),
    ### so the new weights must beat the defaults on new data, not on the data they were fitted to
    test = usable[4::5] if len(usable) >= 5 * HOLDOUT_MIN else []
    train = [r for i, r in enumerate(usable) if i % 5 != 4] if test else usable
    judge = test or usable
    features, targets = [], []
    for r in train:
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
        rows=len(train),
    )
    error = sum(abs(predict(r, fitted) - r.actual) for r in judge) / len(judge)
    default_error = sum(abs(predict(r, default) - r.actual) for r in judge) / len(judge)
    ### Only take the new weights when they really are better
    if error >= default_error:
        return coach.ExpectationWeights(rows=0, error=default_error, default_error=default_error)
    return coach.ExpectationWeights(
        fitted.form, fitted.average, fitted.win, fitted.table, fitted.rows, round(error, 1), round(default_error, 1)
    )


def history_rows(
    matches: Sequence[Sequence], opponents: dict[int, tuple[str | None, bool]], placements: dict[str, int | None],
    skip_days: set[int] | frozenset[int] = frozenset(),
) -> list[ExpectationRow]:
    """Rows rebuilt from a player's past matches: for every match, what his earlier ones said.

    `matches` are the stored form rows `[matchday, points, minutes, role, ...]` in any order,
    `opponents` maps a matchday to the opponent and whether it was at home. Status and odds of the
    past are unknown: the player counts as available. The table of back then is unknown too, and
    today's would be knowledge of the future, so the table term is left out (0): its weight is
    learned from the logged forecasts only. Matchdays in `skip_days` were logged as real forecasts
    and are not counted twice.
    """
    ordered = sorted((m for m in matches if m and m[0] is not None), key=lambda m: m[0])
    rows = []
    for index in range(3, len(ordered)):
        if int(ordered[index][0]) in skip_days:
            continue
        before = [coach.MatchForm(int(m[1]), int(m[2] or 0) if len(m) > 2 else 0, m[3] if len(m) > 3 else None) for m in ordered[:index]]
        recent = list(reversed(before))[:5]
        played_points = [m.points for m in before if m.played]
        if not played_points:
            continue
        form = coach.form_points([m.points for m in recent if m.played])
        chance = coach.play_probability(recent) or 0.0
        day = int(ordered[index][0])
        _, home = opponents.get(day, (None, None))
        rows.append(
            ExpectationRow(
                form=form,
                average=sum(played_points) / len(played_points),
                chance=chance,
                win=None,
                table=0.0,
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


### ===============================================================================
### Forecast quality on every observed player (E10.00)
### ===============================================================================

### Horizons checked: market value updates after the observation
FORECAST_HORIZONS = (1, 2)


def settle_observation(points: Sequence[Sequence[int]], day: int, value: int) -> tuple[int | None, int | None, bool]:
    """What the value really did 1 and 2 updates after `day`, from the history (days as Kickbase sends
    them). Only exact days count: a gap is no change. Done when both are known, or the history is past
    them with a gap (given up)."""
    by_day = {int(d): int(v) for d, v in points}
    base = by_day.get(day, value)
    actual = [by_day[day + h] - base if day + h in by_day else None for h in FORECAST_HORIZONS]
    last = max(by_day, default=day)
    done = all(a is not None for a in actual) or last > day + max(FORECAST_HORIZONS)
    return actual[0], actual[1], done


def _quantile(values: Sequence[float], share: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[min(int(len(ordered) * share), len(ordered) - 1)], 3)


def forecast_quality(rows: Iterable[tuple[int, int, int, int | None, int | None]]) -> dict:
    """How good the market value forecast was, per horizon: rows are (value, forecast 1, forecast 2,
    actual 1, actual 2). Direction hits count forecasts that are not zero; the ratio actual/forecast is
    the calibration (1.0: right on average); errors are actual minus forecast in percent of the value,
    apart for rising and falling forecasts, because a falling one can drop much further."""
    rows = list(rows)
    result: dict[str, dict] = {}
    for index, horizon in enumerate(FORECAST_HORIZONS):
        pairs = [(r[0], r[1 + index], r[3 + index]) for r in rows if r[3 + index] is not None and r[0] > 0]
        moved = [(v, f, a) for v, f, a in pairs if f != 0]
        stats: dict[str, object] = {"n": len(pairs), "direction_n": len(moved),
                                    "direction_hits": sum(1 for _, f, a in moved if (f > 0) == (a > 0) and a != 0)}
        stats["hit_rate"] = round(stats["direction_hits"] / len(moved), 3) if moved else None
        for side, chosen in (("rising", [p for p in moved if p[1] > 0]), ("falling", [p for p in moved if p[1] < 0])):
            forecast_sum = sum(f for _, f, _ in chosen)
            errors = [(a - f) / v * 100 for v, f, a in chosen]
            stats[side] = {
                "n": len(chosen),
                "ratio": round(sum(a for _, _, a in chosen) / forecast_sum, 3) if forecast_sum else None,
                "error_pct_p5": _quantile(errors, 0.05), "error_pct_p50": _quantile(errors, 0.5),
                "error_pct_p95": _quantile(errors, 0.95), "error_pct_min": round(min(errors), 3) if errors else None,
            }
        stats["mae_pct"] = round(sum(abs(a - f) / v * 100 for v, f, a in pairs) / len(pairs), 3) if pairs else None
        result[f"h{horizon}"] = stats
    return result
