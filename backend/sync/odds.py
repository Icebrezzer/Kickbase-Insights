"""Betting odds of the next matchday, for the expected points and the market cards.

First Kickbase's own (undocumented) bet link of each match is asked. If it carries no odds and a key
for the-odds-api.com is set, that service is used. The raw answers are stored, so the shape of
Kickbase's answer can be looked at on the Status page.
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
import unicodedata
from datetime import datetime, timedelta

import httpx
from sqlalchemy import Engine
from sqlmodel import Session, select

from core import coach
from core.config import Settings
from db.models import Fixture, MatchOdds, Team, utcnow
from kickbase import KickbaseAuthError, KickbaseClient, KickbaseError

log = logging.getLogger(__name__)

ODDS_API = "https://api.the-odds-api.com/v4/sports/{sport}/odds"
### Kickbase's competition ids and the sport keys of the-odds-api.com
SPORTS = {1: "soccer_germany_bundesliga", 2: "soccer_germany_bundesliga2", 3: "soccer_spain_la_liga"}
### Words that say nothing about which club is meant
_NOISE = {"fc", "sv", "vfb", "vfl", "tsg", "sc", "bv", "fsv", "1", "04", "05", "09", "1899", "1846", "de", "borussia", "rb", "cf", "ac"}
_ALIASES = {"munich": "munchen", "cologne": "koln", "monchengladbach": "gladbach", "frankfurt": "eintracht"}


def _tokens(name: str) -> set[str]:
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    words = {_ALIASES.get(w, w) for w in re.split(r"[^a-z0-9]+", plain) if w}
    return {w for w in words if w not in _NOISE} or words


def _similar(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / min(len(ta), len(tb))


def _items(value: object) -> list[dict]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


class OddsService:
    def __init__(self, settings: Settings, engine: Engine):
        self.settings = settings
        self.engine = engine
        self._last: dict[int, datetime] = {}

    def _next_fixtures(self, competition_id: int) -> list[Fixture]:
        now = utcnow()
        with Session(self.engine) as session:
            fixtures = list(session.exec(select(Fixture).where(Fixture.competition_id == competition_id)))
        infos = [coach.FixtureInfo(f.day, f.kickoff, f.status, f.team1_id, f.team2_id, f.id) for f in fixtures]
        upcoming = coach.next_matchday(infos, now)
        if upcoming is None:
            return []
        return [f for f in fixtures if f.day == upcoming.day and f.kickoff and f.kickoff > now]

    async def refresh(self, client: KickbaseClient, competition_id: int, force: bool = False) -> int:
        """Fetches the odds of the next matchday. Returns how many matches have odds."""
        now = utcnow()
        last = self._last.get(competition_id)
        if not force and last and now - last < timedelta(hours=self.settings.odds.refresh_hours):
            return 0
        self._last[competition_id] = now
        fixtures = await asyncio.to_thread(self._next_fixtures, competition_id)
        if not fixtures:
            return 0

        async def kickbase(fixture: Fixture) -> tuple[str, object | None]:
            try:
                return fixture.id, await client.match_betlink(fixture.id)
            except KickbaseAuthError:
                raise
            except KickbaseError as e:
                log.debug("No bet link for match %s: %s", fixture.id, e)
                return fixture.id, None

        answers = dict(await asyncio.gather(*(kickbase(f) for f in fixtures)))
        found: dict[str, tuple[tuple[float, float, float], str, object]] = {}
        for match_id, raw in answers.items():
            odds = coach.find_odds(raw) if raw is not None else None
            if odds:
                found[match_id] = (odds, "kickbase", raw)

        missing = [f for f in fixtures if f.id not in found]
        key = self.settings.odds.api_key.get_secret_value() if self.settings.odds.api_key else None
        if missing and key and competition_id in SPORTS:
            found.update(await self._odds_api(key, competition_id, missing))

        await asyncio.to_thread(self._store, fixtures, found, answers)
        log.info("Odds for %d of %d matches of the next matchday", len(found), len(fixtures))
        return len(found)

    async def _odds_api(self, key: str, competition_id: int, fixtures: list[Fixture]) -> dict:
        try:
            async with httpx.AsyncClient(timeout=15) as http:
                response = await http.get(
                    ODDS_API.format(sport=SPORTS[competition_id]),
                    params={"apiKey": key, "regions": "eu", "markets": "h2h", "oddsFormat": "decimal"},
                )
                response.raise_for_status()
                events = response.json()
        except (httpx.HTTPError, ValueError) as e:
            log.warning("The Odds API failed (%s)", type(e).__name__) # Exception URLs contain the API key.
            return {}
        if not isinstance(events, list):
            return {}
        with Session(self.engine) as session:
            names = {t.id: t.name for t in session.exec(select(Team))}
        result = {}
        for fixture in fixtures:
            home_name, away_name = names.get(fixture.team1_id or "", ""), names.get(fixture.team2_id or "", "")
            best, score = None, 0.0
            for event in events:
                if not isinstance(event, dict):
                    continue
                try:
                    start = datetime.fromisoformat(str(event["commence_time"]).replace("Z", "+00:00"))
                except (KeyError, ValueError):
                    continue
                if start.tzinfo is None or fixture.kickoff is None or abs(start - fixture.kickoff) > timedelta(hours=3):
                    continue
                home, away = event.get("home_team"), event.get("away_team")
                if not isinstance(home, str) or not isinstance(away, str):
                    continue
                home_score, away_score = _similar(home_name, home), _similar(away_name, away)
                if min(home_score, away_score) < 0.5:
                    continue
                points = home_score + away_score
                if points > score:
                    best, score = event, points
            if best is None or score < 0.5:
                continue
            prices: dict[str, list[float]] = {"home": [], "draw": [], "away": []}
            for bookmaker in _items(best.get("bookmakers")):
                for market in _items(bookmaker.get("markets")):
                    if market.get("key") != "h2h":
                        continue
                    for outcome in _items(market.get("outcomes")):
                        name = outcome.get("name")
                        side = "home" if name == best.get("home_team") else "away" if name == best.get("away_team") else "draw" if name == "Draw" else None
                        try:
                            price = float(outcome.get("price", 0))
                        except (ValueError, TypeError):
                            continue
                        if side is not None and math.isfinite(price) and price > 1:
                            prices[side].append(price)
            if all(prices.values()):
                odds = tuple(round(sum(v) / len(v), 2) for v in (prices["home"], prices["draw"], prices["away"]))
                result[fixture.id] = (odds, "the-odds-api", {"event": best.get("id")})
        return result

    def _store(self, fixtures: list[Fixture], found: dict, answers: dict) -> None:
        now = utcnow()
        with Session(self.engine) as session:
            for fixture in fixtures:
                row = session.get(MatchOdds, fixture.id) or MatchOdds(match_id=fixture.id)
                if fixture.id in found:
                    (home, draw, away), source, raw = found[fixture.id]
                    row.home, row.draw, row.away, row.source = home, draw, away, source
                    row.raw = raw if isinstance(raw, dict) else {"answer": raw}
                else:
                    ### Kept to see what Kickbase sends, even without odds
                    raw = answers.get(fixture.id)
                    row.raw = raw if isinstance(raw, dict) else {"answer": raw}
                row.updated_at = now
                session.add(row)
            session.commit()

    def sample(self) -> list[dict]:
        """The latest stored answers, for checking the undocumented bet link."""
        with Session(self.engine) as session:
            rows = session.exec(select(MatchOdds).order_by(MatchOdds.updated_at.desc()).limit(3)).all()
            return [
                {"match_id": r.match_id, "source": r.source, "odds": [r.home, r.draw, r.away], "raw": r.raw}
                for r in rows
            ]
