"""Offline demo benchmark; optional argv[1] selects a baseline backend checkout."""
from __future__ import annotations

import json
import logging
import statistics
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(sys.argv[1]).resolve()) if len(sys.argv) > 1
                else str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlmodel import Session

from api.app import create_app
from core.config import Settings
from db.models import League, utcnow
from kickbase.demo import DEMO_EMAIL, DEMO_PASSWORD


def main():
    with tempfile.TemporaryDirectory() as folder:
        settings = Settings(_env_file=None, demo=True, data_dir=Path(folder),
                            push={"subject": None}, odds={"api_key": None})
        with TestClient(create_app(settings, start_scheduler=False)) as client:
            logging.getLogger().setLevel(logging.ERROR)
            response = client.post("/api/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD})
            assert response.status_code == 200, response.text
            for _ in range(300):
                status = client.get("/api/status").json()
                if status.get("league", {}).get("syncedAt") and not status["sync"]["running"]:
                    break
                time.sleep(0.1)
            else:
                raise AssertionError("Demo sync did not finish")
            state = client.app.state.kbi
            with Session(state.engine) as session:
                league = session.get(League, "4242")
            kb = state.accounts.service
            squad = client.portal.call(kb.manager_squad, "4242", "1001")
            market = client.portal.call(kb.market, "4242")
            row = state.automation.get_settings("1001", "4242")
            row.trader = True
            row.trader_live = False
            queries = []

            def count(*args):
                queries.append(1)

            event.listen(state.engine, "before_cursor_execute", count)
            timings, counts = [], []
            for _ in range(20):
                queries.clear()
                start = time.perf_counter()
                state.automation.trader._plan(league, row, squad, 200_000_000, market, utcnow())
                timings.append((time.perf_counter() - start) * 1000)
                counts.append(len(queries))
            event.remove(state.engine, "before_cursor_execute", count)

            def request(index):
                start = time.perf_counter()
                response = client.get(("/api/market", "/api/players", "/api/managers")[index % 3])
                assert response.status_code == 200, response.text[:200]
                return (time.perf_counter() - start) * 1000

            for i in range(3):
                request(i)
            start = time.perf_counter()
            with ThreadPoolExecutor(max_workers=8) as pool:
                latencies = list(pool.map(request, range(240)))
            elapsed = time.perf_counter() - start
            print(json.dumps({
                "plan_rounds": 20, "plan_median_ms": round(statistics.median(timings), 2),
                "plan_sql_median": statistics.median(counts), "requests": len(latencies), "concurrency": 8,
                "requests_per_second": round(len(latencies) / elapsed, 2),
                "request_median_ms": round(statistics.median(latencies), 2),
                "request_p95_ms": round(sorted(latencies)[int(len(latencies) * 0.95) - 1], 2),
                "errors": 0,
            }, indent=2))


if __name__ == "__main__":
    main()
