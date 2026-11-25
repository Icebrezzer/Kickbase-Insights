"""Everything the expected points and forecasts need from the database, loaded once per answer."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime

from sqlmodel import Session, select

from core import analytics, coach
from db.models import Fixture, MatchOdds, ModelState, PlayerForm, Team


@dataclass
class MatchContext:
    fixtures: list[coach.FixtureInfo]
    placements: dict[str, int | None]
    forms: dict[str, list] = field(default_factory=dict)
    odds: dict[str, tuple[float | None, float | None, float | None]] = field(default_factory=dict)
    upcoming: coach.Matchday | None = None
    day: int = 0
    weights: coach.ExpectationWeights = field(default_factory=coach.ExpectationWeights)

    def fixture_of(self, team_id: str | None) -> coach.FixtureInfo | None:
        return coach.next_fixture_of(team_id, self.fixtures, self.day)

    def recent(self, player_id: str) -> tuple[coach.MatchForm, ...]:
        """The club's last matches from the player's point of view, newest first."""
        rows = self.forms.get(player_id) or []
        return tuple(
            coach.MatchForm(int(r[1]), int(r[2]) if len(r) > 2 else 0, int(r[3]) if len(r) > 3 and r[3] is not None else None)
            for r in rows
        )

    def match_points(self, player_id: str) -> list[tuple[int, int]]:
        """`(market value day, points)` of the matches the player was on the pitch."""
        rows = self.forms.get(player_id) or []
        return [(int(r[4]), int(r[1])) for r in rows if len(r) > 4 and r[4] is not None]

    def win_probability(self, fixture: coach.FixtureInfo | None, team_id: str | None) -> float | None:
        if fixture is None or fixture.id is None or fixture.id not in self.odds:
            return None
        probabilities = coach.win_probabilities(*self.odds[fixture.id])
        if probabilities is None:
            return None
        return probabilities[0] if fixture.team1_id == team_id else probabilities[2]

    def odds_of(self, fixture: coach.FixtureInfo | None) -> tuple[float | None, float | None, float | None] | None:
        if fixture is None or fixture.id is None:
            return None
        return self.odds.get(fixture.id)

    def expectation(
        self, player_id: str, position: int, status: int, team_id: str | None, average_points: int | None
    ) -> coach.Expectation:
        fixture = self.fixture_of(team_id)
        form = coach.FormInput(player_id, position, status, team_id, average_points, self.recent(player_id)[:5])
        return coach.expected_points(
            form, fixture, self.placements, self.win_probability(fixture, team_id), self.weights
        )

    def expectation_ahead(
        self, player_id: str, position: int, status: int, team_id: str | None, average_points: int | None, matches: int = 3
    ) -> float | None:
        """Mean expected points over the club's next `matches` fixtures, by the same model: odds where
        Kickbase has them (the next matchday), the table and home/away for the later ones. None
        without fixtures. The status is taken as it is now."""
        ahead = sorted((f for f in self.fixtures if f.day >= self.day and team_id in (f.team1_id, f.team2_id)), key=lambda f: f.day)[:matches]
        if not ahead:
            return None
        form = coach.FormInput(player_id, position, status, team_id, average_points, self.recent(player_id)[:5])
        values = [
            coach.expected_points(form, f, self.placements, self.win_probability(f, team_id) if f.day == self.day else None, self.weights).expected
            for f in ahead
        ]
        return round(sum(values) / len(values), 1)

    def samples(self, player_id: str) -> int:
        """How many of the club's last five matches the player played: the data behind form and play."""
        return sum(1 for m in self.recent(player_id)[:5] if m.played)


def load_context(
    session: Session, competition_id: int, player_ids: Iterable[str] | None, now: datetime
) -> MatchContext:
    fixtures = [
        coach.FixtureInfo(f.day, f.kickoff, f.status, f.team1_id, f.team2_id, f.id)
        for f in session.exec(select(Fixture).where(Fixture.competition_id == competition_id))
    ]
    placements = {
        t.id: t.placement for t in session.exec(select(Team).where(Team.competition_id == competition_id))
    }
    query = select(PlayerForm.player_id, PlayerForm.matches)
    if player_ids is not None:
        query = query.where(PlayerForm.player_id.in_(list(player_ids)))
    forms = dict(session.exec(query).all())
    upcoming = coach.next_matchday(fixtures, now)
    day = upcoming.day if upcoming else 0
    match_ids = [f.id for f in fixtures if f.day == day and f.id]
    odds = {
        o.match_id: (o.home, o.draw, o.away)
        for o in session.exec(select(MatchOdds).where(MatchOdds.match_id.in_(match_ids)))
        if o.home and o.away
    }
    return MatchContext(fixtures, placements, forms, odds, upcoming, day, learned_weights(session))


def learned_weights(session: Session) -> coach.ExpectationWeights:
    """The expected points weights learned from the real points (sync.learning), if any."""
    row = session.get(ModelState, "expectation")
    data = row.data if row else {}
    if not data or not data.get("rows"):
        return coach.ExpectationWeights()
    fields = coach.ExpectationWeights.__dataclass_fields__
    return coach.ExpectationWeights(**{k: v for k, v in data.items() if k in fields})


def match_day_of(kickoff: datetime) -> int:
    """The market value day whose update is the first one after the match."""
    return analytics.market_value_day(kickoff) + 1
