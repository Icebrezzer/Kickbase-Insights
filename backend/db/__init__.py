"""Module for DB access."""

from __future__ import annotations

import logging
import zlib
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event, inspect, text
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel

from db import models  # noqa: F401  - registers the tables on the metadata
from db.models import SCHEMA_VERSION, SchemaInfo

try:
    import fcntl
except ImportError: # Windows, where the app is only developed
    fcntl = None

log = logging.getLogger(__name__)


def create_db_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        in_memory = ":memory:" in url or url == "sqlite://"
        if not in_memory:
            Path(url.split("///", 1)[1]).parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(
            url,
            connect_args={"check_same_thread": False},
            ### An in-memory database exists per connection, so every thread has to share one
            poolclass=StaticPool if in_memory else None,
        )

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_connection, _record):
            cursor = dbapi_connection.cursor()
            ### WAL lets the API keep reading while a sync writes
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()

        return engine

    return create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5)


def init_db(engine: Engine) -> None:
    """Create tables and apply additive changes; never discard existing user data."""
    tables = set(inspect(engine).get_table_names())
    stored: int | None = None
    if "schemainfo" in tables:
        with Session(engine) as session:
            row = session.get(SchemaInfo, 1)
            stored = row.version if row else None
    elif tables & set(SQLModel.metadata.tables):
        ### Tables from before the schema was versioned
        stored = 1

    if stored is not None and stored > SCHEMA_VERSION:
        raise RuntimeError(
            f"The database was created by a newer Kickbase Insights "
            f"(schema {stored}, this is {SCHEMA_VERSION})."
        )
    pending = range(stored, SCHEMA_VERSION) if stored is not None else range(0)
    if any(version not in _MIGRATIONS for version in pending):
        raise RuntimeError(
            f"Database schema {stored} needs a migration to {SCHEMA_VERSION}. "
            "No data was changed. Back up the database and use a supported migration before upgrading."
        )

    SQLModel.metadata.create_all(engine)
    _add_transfer_ids(engine)
    _add_missing_columns(engine)
    ### Migrations run on the current tables, after the additive steps above
    for version in pending:
        log.warning("Migrating the database from schema %s to %s", version, version + 1)
        _MIGRATIONS[version](engine)
    with Session(engine) as session:
        session.merge(SchemaInfo(id=1, version=SCHEMA_VERSION))
        session.commit()
    log.info("Database ready (%s)", engine.url.render_as_string(hide_password=True))


def _add_transfer_ids(engine: Engine) -> None:
    """Add the manager ids to transfers of a database that only has their names.

    The names give the ids of the current managers right away, so nothing looks wrong until the next
    sync. That sync then reads every transfer list again, which also finds what a rename had cut off.
    """
    if "buyer_id" in {column["name"] for column in inspect(engine).get_columns("transfer")}:
        return
    log.info("Adding the manager ids to the stored transfers")
    with engine.begin() as connection:
        for side in ("buyer", "seller"):
            connection.exec_driver_sql(f"ALTER TABLE transfer ADD COLUMN {side}_id VARCHAR")
            ### MIN because two managers can share a name, the next sync sorts that out
            connection.exec_driver_sql(
                f"UPDATE transfer SET {side}_id = (SELECT MIN(manager.id) FROM manager "
                f"WHERE manager.league_id = transfer.league_id AND manager.name = transfer.{side})"
            )
        connection.exec_driver_sql("UPDATE leagueseason SET transfers_complete_since = NULL")


def _migrate_1_to_2(engine: Engine) -> None:
    """Schema 2 stopped storing leagues in another game mode than Classic.

    The database does not know a league's game mode, so the stored sessions end instead: memberships
    are only synced with a session, and the next login keeps only the Classic leagues. Everything
    synced, learned or set by the users stays.
    """
    with engine.begin() as connection:
        connection.exec_driver_sql("DELETE FROM usersession")


### Schema version -> step that brings a database of that version to the next one
_MIGRATIONS = {1: _migrate_1_to_2}


### Columns added to tables after they were first created: table -> column -> SQL type and default
_LATER_COLUMNS = {
    "userleague": {
        "inactive": "BOOLEAN NOT NULL DEFAULT FALSE",
        ### NULL: the server's setting applies
        "analysis_squad_limit": "INTEGER",
        "analysis_club_limit": "INTEGER",
    },
    "userautomation": {"listing_alerts": "BOOLEAN DEFAULT TRUE", "sell_alerts": "BOOLEAN DEFAULT TRUE"},
}


def _add_missing_columns(engine: Engine) -> None:
    """Adds columns of the manager tools that came after their table, keeping the stored rows."""
    inspector = inspect(engine)
    for table, columns in _LATER_COLUMNS.items():
        if table not in inspector.get_table_names():
            continue
        present = {column["name"] for column in inspector.get_columns(table)}
        with engine.begin() as connection:
            for name, definition in columns.items():
                if name not in present:
                    log.info("Adding column %s.%s", table, name)
                    connection.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def session_scope(engine: Engine) -> Iterator[Session]:
    with Session(engine) as session:
        yield session


@contextmanager
def exclusive(engine: Engine, name: str) -> Iterator[None]:
    """Hold a lock that every process using this database shares, e.g. the server and `main.py sync`.

    PostgreSQL: a transaction advisory lock, released with the transaction even if the process dies.
    SQLite: an flock on a file next to the database. An in-memory database has only one process.
    """
    if engine.dialect.name == "postgresql":
        with engine.begin() as connection:
            connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": zlib.crc32(name.encode())})
            yield
        return
    path = engine.url.database
    if engine.dialect.name != "sqlite" or not path or path == ":memory:" or fcntl is None:
        yield
        return
    with open(f"{path}.{name}.lock", "a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
