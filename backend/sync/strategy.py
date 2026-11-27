"""Stored trader configurations per user and league (E02.03): versioned, append-only, one active.

The first read of a league without a stored version takes the options of 2.0 (UserAutomation.
trader_options) as version 1, so nothing is lost and no start-up migration is needed. Every activation
writes the options back to trader_options as well: the settings page, an older release and every
reader of the options see the same values.
"""

from __future__ import annotations

from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from core import strategy_config as sc
from core import trader as t
from db import exclusive
from db.models import StrategyConfig, UserAutomation, utcnow

LOCK = "strategy-config"


class ConfigConflict(Exception):
    """The active version changed since the caller read it."""


class StrategyStore:
    def __init__(self, engine: Engine):
        self.engine = engine

    def _active(self, session: Session, user_id: str, league_id: str) -> StrategyConfig | None:
        return session.exec(select(StrategyConfig).where(
            StrategyConfig.user_id == user_id, StrategyConfig.league_id == league_id, StrategyConfig.active == True,  # noqa: E712
        ).order_by(StrategyConfig.version.desc())).first()

    def active(self, user_id: str, league_id: str) -> StrategyConfig:
        """The active configuration; the first time the options of 2.0 become version 1."""
        with Session(self.engine) as session:
            row = self._active(session, user_id, league_id)
            if row is not None:
                return row
            settings = session.get(UserAutomation, (user_id, league_id))
            first = StrategyConfig(
                user_id=user_id, league_id=league_id, version=1, active=True, created_by="migration",
                data=sc.from_options(t.Options.load(settings.trader_options if settings else None)),
                note="Übernommen aus den bisherigen Einstellungen",
            )
            session.add(first)
            try:
                session.commit()
            except IntegrityError:
                ### Another round seeded it at the same moment: theirs counts
                session.rollback()
                return self._active(session, user_id, league_id)
            session.refresh(first)
            return first

    def options(self, user_id: str, league_id: str) -> tuple[int, t.Options]:
        row = self.active(user_id, league_id)
        return row.version, sc.to_options(row.data)

    def activate(self, user_id: str, league_id: str, data: dict, created_by: str, note: str = "",
                 expected: int | None = None) -> StrategyConfig:
        """Stores `data` (validated by the caller) as the new active version, in one transaction under a
        lock all processes share. With `expected`, refuses when the active version is another one."""
        current = self.active(user_id, league_id)
        with exclusive(self.engine, LOCK), Session(self.engine) as session:
            active = self._active(session, user_id, league_id)
            if expected is not None and (active is None or active.version != expected):
                raise ConfigConflict(f"Aktive Version ist {active.version if active else '–'}, nicht {expected}")
            newest = session.exec(select(StrategyConfig.version).where(
                StrategyConfig.user_id == user_id, StrategyConfig.league_id == league_id,
            ).order_by(StrategyConfig.version.desc())).first() or current.version
            if active is not None:
                active.active = False
                session.add(active)
            row = StrategyConfig(user_id=user_id, league_id=league_id, version=newest + 1, active=True,
                                 schema_version=sc.SCHEMA_VERSION, data=data, created_by=created_by, note=note)
            session.add(row)
            settings = session.get(UserAutomation, (user_id, league_id)) or UserAutomation(user_id=user_id, league_id=league_id)
            settings.trader_options = sc.to_options(data).__dict__
            settings.updated_at = utcnow()
            session.add(settings)
            session.commit()
            session.refresh(row)
            return row

    def follow_options(self, user_id: str, league_id: str, opts: t.Options, created_by: str) -> StrategyConfig:
        """After the options were changed the 2.0 way (settings page, options import): a new version when
        they differ from the active one, otherwise the active one."""
        current = self.active(user_id, league_id)
        if sc.to_options(current.data) == opts:
            return current
        data = {**current.data, **{k: v for k, v in sc.from_options(opts).items() if k != "schema_version"}}
        return self.activate(user_id, league_id, data, created_by)

    def history(self, user_id: str, league_id: str, limit: int = 50) -> list[StrategyConfig]:
        self.active(user_id, league_id)
        with Session(self.engine) as session:
            return list(session.exec(select(StrategyConfig).where(
                StrategyConfig.user_id == user_id, StrategyConfig.league_id == league_id,
            ).order_by(StrategyConfig.version.desc()).limit(limit)).all())

    def version(self, user_id: str, league_id: str, version: int) -> StrategyConfig | None:
        with Session(self.engine) as session:
            return session.get(StrategyConfig, (user_id, league_id, version))
