"""The manager tools: matchday deadline, expected points, best eleven, budget rescue, market value
forecast and the club limit.

Everything here is a pure function on plain values. Nothing reads the database or Kickbase, so the
formulas can be tested on their own and changed without a migration (see DEVELOPMENT.md).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

### ===============================================================================
### Matchday deadline
### ===============================================================================

### The lineup has to stand one minute before the first kick-off of a matchday
DEADLINE_MARGIN = timedelta(minutes=1)
### A match without a final whistle from Kickbase counts as over this long after its kick-off
MATCH_LENGTH = timedelta(hours=2, minutes=30)

MATCH_RUNNING, MATCH_FINISHED = 1, 2


@dataclass(frozen=True)
class FixtureInfo:
    day: int
    kickoff: datetime | None
    status: int | None
    team1_id: str | None
    team2_id: str | None


@dataclass(frozen=True)
class Matchday:
    day: int
    first_kickoff: datetime
    last_kickoff: datetime
    deadline: datetime


def _over(fixture: FixtureInfo, now: datetime) -> bool:
    if fixture.status == MATCH_FINISHED:
        return True
    return fixture.kickoff is not None and fixture.kickoff + MATCH_LENGTH <= now


def _running(fixture: FixtureInfo, now: datetime) -> bool:
    if fixture.status == MATCH_RUNNING:
        return True
    if fixture.kickoff is None or fixture.status == MATCH_FINISHED:
        return False
    return fixture.kickoff <= now < fixture.kickoff + MATCH_LENGTH


def _matchdays(fixtures: Iterable[FixtureInfo]) -> dict[int, list[FixtureInfo]]:
    days: dict[int, list[FixtureInfo]] = defaultdict(list)
    for fixture in fixtures:
        if fixture.kickoff is not None:
            days[fixture.day].append(fixture)
    return days


def next_matchday(fixtures: Iterable[FixtureInfo], now: datetime) -> Matchday | None:
    """The next matchday whose first match has not kicked off yet, with its lineup deadline.

    Midweek matchdays are found the same way, the deadline always follows the real first kick-off.
    A single match moved far into the future (a replay) does not count as a matchday of its own:
    the day is taken by its earliest kick-off.
    """
    for day, matches in sorted(_matchdays(fixtures).items()):
        first = min(m.kickoff for m in matches if m.kickoff)
        if first > now:
            last = max(m.kickoff for m in matches if m.kickoff)
            return Matchday(day, first, last, first - DEADLINE_MARGIN)
    return None


### Matches this long after a matchday's first kick-off belong to it. Later ones are replays.
MATCHDAY_SPAN = timedelta(days=4)


def live_matchday(fixtures: Iterable[FixtureInfo], now: datetime) -> int | None:
    """The matchday that has started and still has regular matches to play, if any.

    A replay moved weeks later does not keep its old matchday "live", so it does not block the lineup.
    """
    for day, matches in sorted(_matchdays(fixtures).items()):
        first = min(m.kickoff for m in matches if m.kickoff)
        if first > now:
            continue
        regular = [m for m in matches if m.kickoff and m.kickoff <= first + MATCHDAY_SPAN]
        if not all(_over(m, now) for m in regular):
            return day
    return None


def lineup_open(fixtures: Sequence[FixtureInfo], now: datetime) -> bool:
    """True between the end of one matchday and the deadline of the next one."""
    upcoming = next_matchday(fixtures, now)
    return upcoming is not None and now < upcoming.deadline and live_matchday(fixtures, now) is None


def next_fixture_of(team_id: str | None, fixtures: Iterable[FixtureInfo], day: int) -> FixtureInfo | None:
    if team_id is None:
        return None
    for fixture in fixtures:
        if fixture.day == day and team_id in (fixture.team1_id, fixture.team2_id):
            return fixture
    return None


### ===============================================================================
### Expected points
### ===============================================================================

### How likely a player with this Kickbase status plays. Anything not listed (injured, rehab,
### suspended, left the league, absent) scores nothing.
STATUS_AVAILABILITY = {0: 1.0, 2: 0.6}
STATUS_REASONS = {
    1: "verletzt",
    2: "angeschlagen",
    4: "im Aufbautraining",
    8: "rot gesperrt",
    16: "gelb-rot gesperrt",
    32: "Gelbsperre",
    128: "nicht mehr in der Liga",
    256: "abwesend",
}
### Newest match first
FORM_WEIGHTS = (5, 4, 3, 2, 1)
FORM_SHARE = 0.6
### The strongest opponent lowers, the weakest raises the expectation by this much
OPPONENT_SPREAD = 0.15
HOME_BONUS = 0.05


@dataclass(frozen=True)
class FormInput:
    player_id: str
    position: int
    status: int
    team_id: str | None
    average_points: int | None
    ### Points of the club's last matches, newest first. 0 when the player was not on the pitch.
    recent_points: tuple[int, ...] = ()


@dataclass(frozen=True)
class Expectation:
    player_id: str
    expected: float
    form: float | None
    season_average: float | None
    availability: float
    opponent_factor: float
    opponent_id: str | None
    home: bool | None
    reasons: tuple[str, ...] = ()


def form_points(recent: Sequence[int]) -> float | None:
    if not recent:
        return None
    pairs = list(zip(FORM_WEIGHTS, recent, strict=False))
    return sum(w * p for w, p in pairs) / sum(w for w, _ in pairs)


def opponent_factor(placement: int | None, teams: int, home: bool | None) -> float:
    """1.0 for an average opponent, more against the bottom of the table, less against the top."""
    factor = 1.0
    if placement is not None and teams > 1:
        factor += OPPONENT_SPREAD * (2 * (placement - 1) / (teams - 1) - 1)
    if home is True:
        factor += HOME_BONUS
    elif home is False:
        factor -= HOME_BONUS
    return factor


def expected_points(
    player: FormInput,
    fixture: FixtureInfo | None,
    placements: Mapping[str, int | None],
) -> Expectation:
    """The points a player is expected to score on the next matchday.

    Form (weighted last five matches) and season average are blended, then scaled by how likely the
    player plays and by the strength of the opponent. No match means no points.
    """
    reasons: list[str] = []
    form = form_points(player.recent_points)
    average = float(player.average_points) if player.average_points is not None else None
    if form is not None and average is not None:
        base = FORM_SHARE * form + (1 - FORM_SHARE) * average
    else:
        base = form if form is not None else average or 0.0

    availability = STATUS_AVAILABILITY.get(player.status, 0.0)
    if player.status in STATUS_REASONS:
        reasons.append(STATUS_REASONS[player.status])
    elif player.status not in STATUS_AVAILABILITY:
        reasons.append(f"Status {player.status}")

    opponent_id: str | None = None
    home: bool | None = None
    factor = 1.0
    if fixture is None:
        availability = 0.0
        reasons.append("kein Spiel")
    else:
        home = fixture.team1_id == player.team_id
        opponent_id = fixture.team2_id if home else fixture.team1_id
        teams = max((v for v in placements.values() if v is not None), default=18)
        factor = opponent_factor(placements.get(opponent_id or ""), max(teams, 2), home)

    return Expectation(
        player_id=player.player_id,
        expected=round(max(base, 0.0) * availability * factor, 1),
        form=round(form, 1) if form is not None else None,
        season_average=average,
        availability=availability,
        opponent_factor=round(factor, 3),
        opponent_id=opponent_id,
        home=home,
        reasons=tuple(reasons),
    )


### ===============================================================================
### Best eleven
### ===============================================================================

### The formations Kickbase allows: defenders - midfielders - forwards, plus one goalkeeper
FORMATIONS = ("3-4-3", "3-5-2", "3-6-1", "4-2-4", "4-3-3", "4-4-2", "4-5-1", "5-2-3", "5-3-2", "5-4-1")
### An empty slot is worse than any player. The value only ranks lineups, it is no Kickbase rule.
EMPTY_SLOT = 1000.0
### Keeps the saved lineup when another one is not really better, so it does not flip back and forth
KEEP_BONUS = 0.5


@dataclass(frozen=True)
class LineupCandidate:
    player_id: str
    position: int
    expected: float
    market_value: int = 0


@dataclass(frozen=True)
class Eleven:
    formation: str
    ### Goalkeeper first, then defenders, midfielders and forwards, each by expected points
    player_ids: tuple[str, ...]
    expected: float
    empty_slots: int

    def same_players(self, other_ids: Iterable[str]) -> bool:
        return set(self.player_ids) == {pid for pid in other_ids if pid}


def row_sizes(formation: str) -> dict[int, int]:
    defenders, midfielders, forwards = (int(x) for x in formation.split("-"))
    return {1: 1, 2: defenders, 3: midfielders, 4: forwards}


def best_eleven(players: Sequence[LineupCandidate], keep: Iterable[str] = ()) -> Eleven:
    """The formation and players with the most expected points. Full elevens beat stronger short ones.

    Within a formation the best players of each position are simply the top ones by expected points,
    so trying every formation finds the optimum.
    """
    kept = set(keep)
    by_position: dict[int, list[LineupCandidate]] = defaultdict(list)
    for player in players:
        by_position[player.position].append(player)
    for row in by_position.values():
        row.sort(key=lambda p: (p.expected + (KEEP_BONUS if p.player_id in kept else 0), p.market_value), reverse=True)

    best: tuple[float, Eleven] | None = None
    for formation in FORMATIONS:
        chosen: list[LineupCandidate] = []
        empty = 0
        for position, size in row_sizes(formation).items():
            row = by_position.get(position, [])[:size]
            chosen.extend(row)
            empty += size - len(row)
        expected = sum(p.expected for p in chosen)
        rank = expected + sum(KEEP_BONUS for p in chosen if p.player_id in kept) - empty * EMPTY_SLOT
        if best is None or rank > best[0]:
            eleven = Eleven(formation, tuple(p.player_id for p in chosen), round(expected, 1), empty)
            best = (rank, eleven)
    assert best is not None
    return best[1]


### ===============================================================================
### Budget rescue
### ===============================================================================


@dataclass(frozen=True)
class SellCandidate:
    player_id: str
    position: int
    expected: float
    ### What a sale is expected to bring. Kickbase's instant sale price is not known beforehand.
    value: int


@dataclass(frozen=True)
class RescuePlan:
    sales: tuple[str, ...]
    budget_after: int
    expected_before: float
    expected_after: float
    ### False when even selling everything sellable does not reach a balance of zero
    enough: bool

    @property
    def expected_loss(self) -> float:
        return round(self.expected_before - self.expected_after, 1)


def _eleven_score(players: Sequence[SellCandidate]) -> float:
    eleven = best_eleven([LineupCandidate(p.player_id, p.position, p.expected, p.value) for p in players])
    return eleven.expected - eleven.empty_slots * EMPTY_SLOT


def rescue_sales(budget: int, squad: Sequence[SellCandidate], protected: Iterable[str] = ()) -> RescuePlan:
    """The sales that bring the balance back to zero or above with the least loss of expected points.

    Greedy: each step sells the player with the smallest loss per euro, then sales that turned out
    unnecessary are taken back. The squad is small, so every step simply recomputes the best eleven.
    """
    keep = set(protected)
    remaining = [p for p in squad if p.value > 0]
    before = _eleven_score(squad)
    sold: list[SellCandidate] = []
    balance = budget

    while balance < 0:
        current = _eleven_score([p for p in squad if p not in sold])
        options = []
        for player in remaining:
            if player.player_id in keep or player in sold:
                continue
            without = _eleven_score([p for p in squad if p not in sold and p is not player])
            loss = max(current - without, 0.0)
            options.append((loss / player.value, -player.value, player))
        if not options:
            break
        _, _, choice = min(options, key=lambda o: (o[0], o[1]))
        sold.append(choice)
        balance += choice.value

    ### Take back sales that are not needed anymore, the most valuable loss first
    if balance >= 0:
        for player in sorted(sold, key=lambda p: -p.expected):
            if balance - player.value >= 0:
                sold.remove(player)
                balance -= player.value

    after = _eleven_score([p for p in squad if p not in sold])
    return RescuePlan(
        sales=tuple(p.player_id for p in sold),
        budget_after=balance,
        expected_before=round(max(before, 0.0), 1),
        expected_after=round(max(after, 0.0), 1),
        enough=balance >= 0,
    )


### ===============================================================================
### Market value forecast
### ===============================================================================
###
### Kickbase does not publish how it sets market values. BaseXI's "KI-Trend" follows the last change
### very closely (correlation 0.98, about 1.07 times the last change in November 2026), with a pull
### back after long falls. This model has the same shape, but learns its weights from the stored
### histories of all players every day, so it adapts to what Kickbase really does. Changes are
### relative to the market value, so cheap and expensive players weigh the same.

### Features: the last three daily changes and the average of the four before
FEATURE_NAMES = ("d1", "d2", "d3", "d4_7")
### Used until enough history is stored to learn from. Close to BaseXI's behaviour.
DEFAULT_WEIGHTS = (1.05, 0.0, 0.0, -0.05)
TRAINING_DAYS = 90
MIN_TRAINING_ROWS = 2000
### A relative change beyond this is a data error or a transfer from abroad, it is left out of training
MAX_RELATIVE_CHANGE = 0.25


@dataclass(frozen=True)
class ForecastModel:
    weights: tuple[float, ...] = DEFAULT_WEIGHTS
    rows: int = 0 # Training rows, 0 for the default weights
    ### Mean absolute error on the training data, of this model and of "same change as yesterday"
    error: float | None = None
    naive_error: float | None = None

    @property
    def learned(self) -> bool:
        return self.rows > 0


@dataclass(frozen=True)
class Forecast:
    next_change: int
    ### Expected change against today's value after 1, 2, ... updates
    projection: tuple[int, ...]
    ### Days in a row the value moved in the same direction, negative for falling
    streak: int


def daily_changes(points: Sequence[Sequence[int]]) -> list[int]:
    """Changes between consecutive history days, oldest first. Gaps in the history are skipped."""
    changes = []
    for (day_a, value_a), (day_b, value_b) in zip(points, points[1:], strict=False):
        if day_b - day_a == 1:
            changes.append(value_b - value_a)
    return changes


def streak_of(changes: Sequence[int]) -> int:
    streak = 0
    for change in reversed(changes):
        if change == 0 or (streak > 0 and change < 0) or (streak < 0 and change > 0):
            break
        streak += 1 if change > 0 else -1
    return streak


def _relative_series(points: Sequence[Sequence[int]]) -> list[float | None]:
    """Relative daily changes, oldest first. None where a day is missing."""
    series: list[float | None] = []
    for (day_a, value_a), (day_b, value_b) in zip(points, points[1:], strict=False):
        if day_b - day_a != 1 or value_a <= 0:
            series.append(None)
        else:
            series.append((value_b - value_a) / value_a)
    return series


def _features(changes: Sequence[float]) -> list[float] | None:
    """The features from the last seven relative changes, newest last."""
    if len(changes) < 7:
        return None
    return [changes[-1], changes[-2], changes[-3], sum(changes[-7:-3]) / 4]


def _predict(model: ForecastModel, features: Sequence[float]) -> float:
    return sum(w * f for w, f in zip(model.weights, features, strict=True))


def fit_forecast(histories: Iterable[Sequence[Sequence[int]]], training_days: int = TRAINING_DAYS) -> ForecastModel:
    """Learns the weights from the stored histories: for every day, the next change from the ones before."""
    rows: list[list[float]] = []
    targets: list[float] = []
    for points in histories:
        series = _relative_series(points[-(training_days + 9) :])
        for end in range(7, len(series)):
            window = series[end - 7 : end]
            target = series[end]
            if target is None or any(c is None for c in window):
                continue
            if abs(target) > MAX_RELATIVE_CHANGE or any(abs(c) > MAX_RELATIVE_CHANGE for c in window):  # type: ignore[arg-type]
                continue
            features = _features(window)  # type: ignore[arg-type]
            assert features is not None
            rows.append(features)
            targets.append(target)
    if len(rows) < MIN_TRAINING_ROWS:
        return ForecastModel()
    from core.analytics import least_squares

    weights = least_squares(rows, targets)
    if weights is None:
        return ForecastModel()
    model = ForecastModel(tuple(round(w, 4) for w in weights), len(rows))
    error = sum(abs(_predict(model, r) - t) for r, t in zip(rows, targets, strict=True)) / len(rows)
    naive = sum(abs(r[0] - t) for r, t in zip(rows, targets, strict=True)) / len(rows)
    return ForecastModel(model.weights, model.rows, error, naive)


def forecast(points: Sequence[Sequence[int]], model: ForecastModel | None = None, horizon: int = 3) -> Forecast | None:
    """The expected change of the next market value update, and a projection for the updates after.

    The projection feeds every forecast change back in as if it had happened.
    """
    model = model or ForecastModel()
    if len(points) < 2 or points[-1][1] <= 0:
        return None
    series = [c for c in _relative_series(points[-12:]) if c is not None]
    if len(series) < 7:
        return None
    value = float(points[-1][1])
    start = value
    changes = list(series)
    projection = []
    for _ in range(horizon):
        features = _features(changes)
        assert features is not None
        change = max(-MAX_RELATIVE_CHANGE, min(MAX_RELATIVE_CHANGE, _predict(model, features)))
        value *= 1 + change
        changes.append(change)
        projection.append(round(value - start))
    return Forecast(projection[0], tuple(projection), streak_of(daily_changes(points)))


def updates_until(deadline: datetime | None, now: datetime, update_hour: int = 22, tz=None) -> int:
    """How many daily market value updates (22:00 German time) happen from now until `deadline`."""
    if deadline is None or deadline <= now:
        return 0
    from core.analytics import MARKET_VALUE_TIMEZONE

    zone = tz or MARKET_VALUE_TIMEZONE
    local = now.astimezone(zone)
    update = local.replace(hour=update_hour, minute=0, second=0, microsecond=0)
    if update <= local:
        update += timedelta(days=1)
    count = 0
    while update < deadline.astimezone(zone):
        count += 1
        update += timedelta(days=1)
    return count


### ===============================================================================
### Club limit
### ===============================================================================

### A manager may own at most this many players of the same club (league setting)
MAX_PER_CLUB = 3


@dataclass(frozen=True)
class Rival:
    manager_id: str
    club_players: int
    balance: int | None = None
    max_bid: int | None = None


@dataclass
class ClubCounts:
    counts: dict[str, Counter] = field(default_factory=dict)

    @classmethod
    def build(cls, owners: Iterable[tuple[str, str | None]]) -> ClubCounts:
        """`owners` are `(manager_id, team_id)` pairs, one per squad player."""
        counts: dict[str, Counter] = defaultdict(Counter)
        for manager_id, team_id in owners:
            if team_id:
                counts[manager_id][team_id] += 1
        return cls(dict(counts))

    def of(self, manager_id: str, team_id: str | None) -> int:
        return self.counts.get(manager_id, Counter()).get(team_id or "", 0)

    def can_buy(self, manager_id: str, team_id: str | None, limit: int = MAX_PER_CLUB) -> bool:
        return self.of(manager_id, team_id) < limit


def rivals_for(
    team_id: str | None,
    price: int | None,
    managers: Iterable[str],
    clubs: ClubCounts,
    max_bids: Mapping[str, int] | None = None,
    balances: Mapping[str, int] | None = None,
    limit: int = MAX_PER_CLUB,
) -> list[Rival]:
    """The managers who can still bid for a player of `team_id`.

    The club limit always applies. With `max_bids` known, a manager who cannot afford `price` is left
    out as well. The richest rivals come first.
    """
    result = []
    for manager_id in managers:
        if not clubs.can_buy(manager_id, team_id, limit):
            continue
        max_bid = max_bids.get(manager_id) if max_bids is not None else None
        if max_bids is not None and price is not None and (max_bid is None or max_bid < price):
            continue
        balance = balances.get(manager_id) if balances is not None else None
        result.append(Rival(manager_id, clubs.of(manager_id, team_id), balance, max_bid))
    result.sort(key=lambda r: (-(r.max_bid or 0), r.club_players))
    return result
