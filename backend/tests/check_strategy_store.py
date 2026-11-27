"""Stored strategy configurations (E02.03): version 1 from the 2.0 options, append-only, one active,
conflicts refused, options written back, leagues and users apart.

    python tests/check_strategy_store.py
"""

from __future__ import annotations

import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import Session, select  # noqa: E402

from core import strategy_config as sc  # noqa: E402
from core import trader as t  # noqa: E402
from db import create_db_engine, init_db  # noqa: E402
from db.models import StrategyConfig, UserAutomation  # noqa: E402
from sync.strategy import ConfigConflict, StrategyStore  # noqa: E402

passed = 0


def ok(condition: bool, label: str) -> None:
    global passed
    if not condition:
        raise SystemExit(f"FAILED: {label}")
    passed += 1


def main() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
        engine = create_db_engine(f"sqlite:///{Path(folder) / 'store.db'}")
        init_db(engine)
        ### Settings of 2.0, as a running installation has them
        with Session(engine) as s:
            s.add(UserAutomation(user_id="u", league_id="l", trader=True, trader_options={"min_gain": 10.0, "reserve": 2_000_000, "sell_ratio": 100}))
            s.add(UserAutomation(user_id="u", league_id="other", trader_options={"min_gain": 3.0}))
            s.commit()
        store = StrategyStore(engine)

        ### Version 1 is the 2.0 options, created once
        first = store.active("u", "l")
        opts = sc.to_options(first.data)
        ok(first.version == 1 and first.created_by == "migration" and first.active, "version 1 from the stored options")
        ok(opts.min_gain == 10.0 and opts.reserve == 2_000_000 and opts.sell_ratio == 100 and opts.daily_bids == 6, "every value kept")
        ok(store.active("u", "l").version == 1, "a second read creates nothing")
        ok(store.active("nobody", "l").version == 1 and sc.to_options(store.active("nobody", "l").data) == t.Options(), "no settings: the defaults")

        ### A new version: the old one stays, inactive; the options are written back for 2.0 readers
        data, errors = sc.validate({"schema_version": 1, "limits": {"daily_bids": 9}}, first.data)
        ok(not errors, "valid change")
        second = store.activate("u", "l", data, "config", "mehr Gebote", expected=1)
        with Session(engine) as s:
            rows = s.exec(select(StrategyConfig).where(StrategyConfig.user_id == "u", StrategyConfig.league_id == "l")).all()
            settings = s.get(UserAutomation, ("u", "l"))
        ok(second.version == 2 and [r.version for r in rows if r.active] == [2] and len(rows) == 2, "append-only, exactly one active")
        ok(settings.trader_options["daily_bids"] == 9 and settings.trader_options["min_gain"] == 10.0 and settings.trader, "options written back, switches untouched")
        ok(store.version("u", "l", 1).data == first.data, "the old version is kept as it was")
        ok(store.options("u", "l") == (2, t.Options.load(settings.trader_options)), "options of the active version")

        ### Somebody else changed it meanwhile: refused, nothing written
        try:
            store.activate("u", "l", data, "config", expected=1)
            ok(False, "a stale version must be refused")
        except ConfigConflict:
            ok(store.active("u", "l").version == 2, "a stale version is refused, nothing written")

        ### Two at once with the same expected version: exactly one wins
        results: list[str] = []

        def attempt(bids: int) -> None:
            change, _ = sc.validate({"schema_version": 1, "limits": {"daily_bids": bids}}, second.data)
            try:
                store.activate("u", "l", change, "config", expected=2)
                results.append("won")
            except ConfigConflict:
                results.append("conflict")

        threads = [threading.Thread(target=attempt, args=(n,)) for n in (3, 4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        ok(sorted(results) == ["conflict", "won"] and store.active("u", "l").version == 3, f"one of two concurrent changes wins ({results})")

        ### Options changed the 2.0 way: a new version only when they differ
        before = store.active("u", "l").version
        same = store.follow_options("u", "l", sc.to_options(store.active("u", "l").data), "settings")
        ok(same.version == before, "unchanged options make no version")
        changed = store.follow_options("u", "l", t.Options.load({**sc.to_options(same.data).__dict__, "reserve": 0}), "settings")
        ok(changed.version == before + 1 and changed.created_by == "settings" and sc.to_options(changed.data).reserve == 0, "changed options make a version")
        ok(sc.get(changed.data, "profit.hold_updates") == t.PROFIT_HOLD, "fixed rules stay in the stored data")

        ### Other league and other user apart
        ok(sc.to_options(store.active("u", "other").data).min_gain == 3.0 and store.active("u", "other").version == 1, "leagues apart")
        ok(len(store.history("u", "l")) == changed.version and store.history("u", "l")[0].version == changed.version, "history newest first")
        ok(len(store.history("x", "l")) == 1, "users apart")
        ### init_db again keeps everything
        init_db(engine)
        ok(store.active("u", "l").version == changed.version, "a restart keeps the versions")
        engine.dispose() # Windows keeps an open database file
    print(f"All {passed} strategy store checks passed.")


if __name__ == "__main__":
    main()
