"""Kickbase's achievements and their prize money, worked out for every manager from the league's data.

Kickbase only tells a manager his own achievements. The others' are needed for their balances: the
prize money of a season easily reaches tens of millions. The rules below are the ones Kickbase shows in
the app (as listed by BaseXI in November 2026). Only the current season is counted.

Kinds of rules:
- `each`: paid for every occurrence (every matchday win, every matchday with 1,000 points, ...)
- `milestone`: paid once when a count is reached (3 matchday wins, 5,000 season points, ...)
- `once_per_league`: a milestone that is paid only once in the life of the league. With a league that
  is never reset, a manager may have got it in an earlier season already; it is counted anyway and
  marked as such.

Not workable from the stored data: "Tormaschine" (the goals of an eleven are not stored). It is listed
with a count of None.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Rule:
    key: str
    group: str
    name: str
    description: str
    reward: int
    kind: str # each, milestone, once_per_league
    threshold: float = 0


RULES: tuple[Rule, ...] = (
    Rule("md_win", "Spieltagssiege", "Spieltagssieger", "Werde Spieltagssieger", 1_000_000, "each"),
    Rule("md_win_3", "Spieltagssiege", "Spieltagssieger Bronze", "Werde 3x Spieltagssieger", 500_000, "milestone", 3),
    Rule("md_win_5", "Spieltagssiege", "Spieltagssieger Silber", "Werde 5x Spieltagssieger", 1_000_000, "milestone", 5),
    Rule("md_win_10", "Spieltagssiege", "Spieltagssieger Gold", "Werde 10x Spieltagssieger", 1_500_000, "milestone", 10),
    Rule("md_win_25", "Spieltagssiege", "The Special One", "Werde 25x Spieltagssieger pro Saison", 2_000_000, "milestone", 25),
    Rule("md_500", "Spieltagspunkte", "Spieltagspunkte Bronze", "500 Punkte an einem Spieltag", 100_000, "once_per_league", 500),
    Rule("md_1000", "Spieltagspunkte", "Spieltagspunkte Silber", "1.000 Punkte an einem Spieltag", 250_000, "each", 1000),
    Rule("md_1500", "Spieltagspunkte", "Spieltagspunkte Gold", "1.500 Punkte an einem Spieltag", 1_000_000, "each", 1500),
    Rule("md_2000", "Spieltagspunkte", "Jahrhundertspiel", "2.000 Punkte an einem Spieltag", 2_000_000, "each", 2000),
    Rule("season_1000", "Saisonpunkte", "Saisonpunkte Bronze", "1.000 Saisonpunkte", 100_000, "once_per_league", 1000),
    Rule("season_5000", "Saisonpunkte", "Saisonpunkte Silber", "5.000 Saisonpunkte", 250_000, "once_per_league", 5000),
    Rule("season_15000", "Saisonpunkte", "Saisonpunkte Gold", "15.000 Saisonpunkte", 500_000, "once_per_league", 15000),
    Rule("season_30000", "Saisonpunkte", "Saisonpunkte Platin", "30.000 Saisonpunkte", 1_000_000, "once_per_league", 30000),
    Rule("season_40000", "Saisonpunkte", "Weltpokalsieger", "40.000 Saisonpunkte", 2_000_000, "once_per_league", 40000),
    Rule("player_200", "Spieler-Leistungen", "Topscorer", "Ein Spieler der Elf holt 200 Punkte", 100_000, "each", 200),
    Rule("goals", "Spieler-Leistungen", "Tormaschine", "Die Elf erzielt die meisten Tore der Liga", 250_000, "each"),
    Rule("player_300", "Spieler-Leistungen", "Matchwinner", "Ein Spieler der Elf holt 300 Punkte", 500_000, "each", 300),
    Rule("player_400", "Spieler-Leistungen", "Weltklasse", "Ein Spieler der Elf holt 400 Punkte", 1_000_000, "each", 400),
    Rule("player_500", "Spieler-Leistungen", "Fußballgott", "Ein Spieler der Elf holt 500 Punkte", 2_000_000, "each", 500),
    Rule("mvp", "Spieler-Leistungen", "MVP", "Der stärkste Spieler des Spieltags steht in der Elf", 1_000_000, "each"),
    Rule("tv_125", "Mannschaftswert", "Mannschaftswert Bronze", "Mannschaft im Wert von 125 Mio", 100_000, "once_per_league", 125e6),
    Rule("tv_150", "Mannschaftswert", "Mannschaftswert Silber", "Mannschaft im Wert von 150 Mio", 250_000, "once_per_league", 150e6),
    Rule("tv_200", "Mannschaftswert", "Mannschaftswert Gold", "Mannschaft im Wert von 200 Mio", 500_000, "once_per_league", 200e6),
    Rule("tv_250", "Mannschaftswert", "Mannschaftswert Platin", "Mannschaft im Wert von 250 Mio", 1_000_000, "once_per_league", 250e6),
    Rule("tv_350", "Mannschaftswert", "Die Galaktischen", "Mannschaft im Wert von 350 Mio", 2_000_000, "once_per_league", 350e6),
    Rule("deal_first", "Transfers & Händchen", "Erster Deal", "Kaufe oder verkaufe einen Spieler", 100_000, "once_per_league", 1),
    Rule("profit_1", "Transfers & Händchen", "Glückliches Händchen", "1 Mio Gewinn mit einem Spieler", 100_000, "once_per_league", 1e6),
    Rule("profit_3", "Transfers & Händchen", "Bronzenes Händchen", "3 Mio Gewinn mit einem Spieler", 250_000, "each", 3e6),
    Rule("profit_5", "Transfers & Händchen", "Silbernes Händchen", "5 Mio Gewinn mit einem Spieler", 500_000, "each", 5e6),
    Rule("profit_10", "Transfers & Händchen", "Goldenes Händchen", "10 Mio Gewinn mit einem Spieler", 1_000_000, "each", 10e6),
    Rule("profit_25", "Transfers & Händchen", "Königstransfer", "25 Mio Gewinn mit einem Spieler", 2_000_000, "each", 25e6),
    Rule("transfers_50", "Transferkönig", "Transferkönig Bronze", "50 Spieler gekauft oder verkauft", 250_000, "once_per_league", 50),
    Rule("transfers_250", "Transferkönig", "Transferkönig Silber", "250 Spieler gekauft oder verkauft", 500_000, "once_per_league", 250),
    Rule("transfers_500", "Transferkönig", "Transferkönig Gold", "500 Spieler gekauft oder verkauft", 1_000_000, "once_per_league", 500),
    Rule("transfers_1000", "Transferkönig", "F. Magath", "1.000 Spieler gekauft oder verkauft", 2_000_000, "once_per_league", 1000),
    Rule("squad_25", "Sonstiges", "Lange Bank", "Mannschaft mit 25 Spielern", 100_000, "once_per_league", 25),
)

### Kickbase checks the team value once a day; a value just over a threshold may never have been seen
TEAM_VALUE_MARGIN = 0.02


@dataclass(frozen=True)
class ManagerSeason:
    manager_id: str
    ### Per matchday: (day, points, matchday placement, team value)
    matchdays: Sequence[tuple[int, int | None, int | None, int | None]]
    season_points: int
    ### Per matchday the points of each fielded player
    lineup_points: Mapping[int, Sequence[int]] = field(default_factory=dict)
    ### Matchdays on which the strongest player of the matchday was in the eleven
    mvp_days: int = 0
    ### Profit of every closed trade (sale minus purchase)
    profits: Sequence[int] = ()
    transfers: int = 0
    squad_size: int = 0


@dataclass(frozen=True)
class Earned:
    rule: Rule
    count: int | None # None: cannot be worked out from the data
    amount: int


def evaluate(season: ManagerSeason, per_player: bool = False) -> list[Earned]:
    """`per_player`: the player achievements count every player of the eleven above the threshold,
    otherwise once per matchday. Which one Kickbase does is learned (see core.learning.mode_votes)."""
    wins = sum(1 for _, _, placement, _ in season.matchdays if placement == 1)
    day_points = [p for _, p, _, _ in season.matchdays if p is not None]
    best_value = max((v for _, _, _, v in season.matchdays if v), default=0)
    lineups = list(season.lineup_points.values())

    def count(rule: Rule) -> int | None:
        k, t = rule.key, rule.threshold
        if k == "md_win":
            return wins
        if k.startswith("md_win_"):
            return int(wins >= t)
        if k.startswith("md_"):
            hits = sum(1 for p in day_points if p >= t)
            return min(hits, 1) if rule.kind == "once_per_league" else hits
        if k.startswith("season_"):
            return int(season.season_points >= t)
        if k.startswith("player_"):
            if per_player:
                return sum(1 for points in lineups for p in points if p >= t)
            return sum(1 for points in lineups if points and max(points) >= t)
        if k == "goals":
            return None
        if k == "mvp":
            return season.mvp_days
        if k.startswith("tv_"):
            return int(best_value >= t * (1 + TEAM_VALUE_MARGIN))
        if k == "deal_first":
            return int(season.transfers >= 1)
        if k.startswith("profit_"):
            hits = sum(1 for p in season.profits if p >= t)
            return min(hits, 1) if rule.kind == "once_per_league" else hits
        if k.startswith("transfers_"):
            return int(season.transfers >= t)
        if k == "squad_25":
            return int(season.squad_size >= t)
        return None

    result = []
    for rule in RULES:
        n = count(rule)
        result.append(Earned(rule, n, (n or 0) * rule.reward))
    return result


def total(earned: Sequence[Earned]) -> int:
    return sum(e.amount for e in earned)


def mvp_days(lineups: Mapping[int, Sequence[str]], best_by_day: Mapping[int, set[str]]) -> int:
    """Matchdays on which one of the strongest players of the matchday was in the eleven."""
    return sum(1 for day, ids in lineups.items() if best_by_day.get(day) and set(ids) & best_by_day[day])
