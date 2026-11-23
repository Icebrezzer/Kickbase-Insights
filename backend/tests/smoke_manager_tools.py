"""Smoke test of the manager tools against the demo Kickbase. Run from backend/: python tests/smoke_manager_tools.py

Starts the whole app in demo mode with a temporary data folder, waits for the first sync and calls
every new endpoint once. Fails loudly on anything unexpected.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

data_dir = tempfile.mkdtemp()
os.environ.update(
    {
        "KBI_DEMO": "true",
        "KBI_DATA_DIR": data_dir,
        "KBI_PUSH__SUBJECT": "mailto:test@example.org",
        "KBI_ALLOW__BALANCES_USERS": "1001",
    }
)

from fastapi.testclient import TestClient  # noqa: E402

from api.app import create_app  # noqa: E402
from core.config import Settings  # noqa: E402
from kickbase.demo import DEMO_EMAIL, DEMO_PASSWORD  # noqa: E402


def check(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"FAILED: {message}")
    print(f"ok  {message}")


def main() -> None:
    app = create_app(Settings())
    with TestClient(app) as client:
        response = client.post("/api/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD})
        check(response.status_code == 200, f"login ({response.status_code} {response.text[:200]})")

        for _ in range(120):
            status = client.get("/api/status")
            if status.status_code == 200 and status.json().get("league", {}) and status.json()["league"].get("syncedAt"):
                break
            time.sleep(1)
        check(status.status_code == 200 and status.json()["league"]["syncedAt"], "first sync finished")

        market = client.get("/api/market")
        check(market.status_code == 200, f"market ({market.status_code} {market.text[:300]})")
        players = market.json()
        check(len(players) > 0, f"market has {len(players)} players")
        check(all("rivals" in p and "ownClubPlayers" in p for p in players), "market players carry rivals")
        check(
            all(r["clubPlayers"] < 3 for p in players for r in p["rivals"]),
            f"rivals respect the club limit ({sum(len(p['rivals']) for p in players)} rival entries)",
        )
        check(players[0]["rivalsByBudget"] is True, "balances user filters rivals by budget")
        check(any(p.get("forecast") is not None for p in players), "market players carry a forecast")

        everyone = client.get("/api/players")
        check(everyone.status_code == 200, "players")
        check(any(len(p.get("projection") or []) == 3 for p in everyone.json()), "players carry a projection")

        coach = client.get("/api/coach")
        check(coach.status_code == 200, f"coach ({coach.status_code} {coach.text[:300]})")
        view = coach.json()
        check(len(view["squad"]) > 0, f"coach squad has {len(view['squad'])} players")
        check(len(view["bestLineup"]) == 11, f"best eleven has {len(view['bestLineup'])} players")
        check(bool(view["checks"]), "coach has checks")
        print("    checks:", [c["message"] for c in view["checks"]])
        print("    matchday:", view["matchday"], "open:", view["lineupOpen"], "budget:", view["budget"])

        apply = client.post("/api/coach/lineup")
        check(apply.status_code in (200, 400), f"apply lineup answers ({apply.status_code} {apply.text[:300]})")
        if apply.status_code == 200:
            check(apply.json()["confirmed"], "applied lineup is confirmed by the lineup endpoint")

        settings = client.put(
            "/api/automation/settings",
            json={"autoScout": True, "scoutThreshold": 1, "scoutLimit": 5, "autoLineup": True, "deadlineAlerts": True},
        )
        check(settings.status_code == 200 and settings.json()["autoScout"], f"save settings ({settings.status_code})")
        check(client.get("/api/automation/settings").json()["scoutLimit"] == 5, "settings are stored")

        scout = client.post("/api/automation/scout")
        check(scout.status_code == 200, f"scouting run ({scout.status_code} {scout.text[:300]})")
        added = scout.json()["added"]
        check(len(added) <= 5, f"scouting run added {len(added)} players within the limit")
        watch = client.get("/api/watchlist").json()
        check(all(pid in {w["id"] for w in watch} for pid in added), "added players are on the watchlist")

        if added:
            client.delete(f"/api/watchlist/{added[0]}")
            again = client.post("/api/automation/scout")
            check(again.status_code == 200, "second scouting run answers (cooldown)")

        events = client.get("/api/automation/events")
        check(events.status_code == 200, f"events ({len(events.json())})")

        quality = client.get("/api/automation/forecast")
        check(quality.status_code == 200, f"forecast quality {quality.json()}")

        key = client.get("/api/push/key").json()
        check(bool(key.get("publicKey")), "push key is generated")
        sub = client.post(
            "/api/push/subscribe",
            json={"endpoint": "https://push.example.org/abc123456", "p256dh": "x" * 20, "auth": "y" * 8},
        )
        check(sub.status_code == 200 and sub.json()["subscribed"] == 1, "push subscription stored")

        sell_id = view["squad"][-1]["id"]
        before = view["budget"]
        sold = client.post(f"/api/squad/{sell_id}/sell")
        check(sold.status_code == 200, f"instant sale ({sold.status_code} {sold.text[:300]})")
        check(sold.json()["budget"] > before, "budget rose after the sale")
        after = client.get("/api/coach").json()
        check(sell_id not in {p["id"] for p in after["squad"]}, "sold player left the squad")

    print("\nAll manager tool checks passed.")


if __name__ == "__main__":
    main()
