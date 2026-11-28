"""SQLite maintenance latency for one production batch against 100,000 expired decisions."""
import sys
import tempfile
from datetime import timedelta
from pathlib import Path
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import func, insert
from sqlmodel import Session, select

from db import create_db_engine, init_db
from db.models import DecisionSnapshot, ShadowAnalysis, ShadowDaily, utcnow
from sync.shadow_retention import BATCH, archive_batch


def main():
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "benchmark.db"
        engine = create_db_engine(f"sqlite:///{path}")
        init_db(engine)
        now = utcnow()
        sample = DecisionSnapshot(user_id="u", league_id="l", auction="a", first_seen=now - timedelta(days=121),
                                  player_id="p", reason="BUDGET", value=1000000).model_dump()
        replay = ShadowAnalysis(user_id="u", league_id="l", auction="a", player_id="p",
            inputs={"bids": {"standard": 1010000}, "cap": 1020000},
            result={"outcomes": {"standard": "won"}, "exits": {"hold_2": 1030000}}).model_dump()
        with engine.begin() as conn:
            for start in range(0, 100000, 1000):
                conn.execute(insert(DecisionSnapshot), [dict(sample, player_id=str(i)) for i in range(start, start+1000)])
                conn.execute(insert(ShadowAnalysis), [dict(replay, player_id=str(i)) for i in range(start, start+1000)])
        with Session(engine) as session:
            start = perf_counter()
            assert archive_batch(session, "u", "l", now) == BATCH
            session.commit()
            elapsed = perf_counter() - start
            assert session.exec(select(func.sum(ShadowDaily.count))).one() == BATCH
            assert session.exec(select(func.count()).select_from(DecisionSnapshot)).one() == 100000 - BATCH
            print(f"100000 snapshots, batch={BATCH}, commit={elapsed:.4f}s, DB={path.stat().st_size} bytes")
            assert elapsed < 1


if __name__ == "__main__":
    main()
