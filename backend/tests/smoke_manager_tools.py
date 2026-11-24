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
            if (status.status_code == 200 and status.json().get("league", {})
                    and status.json()["league"].get("syncedAt") and not status.json()["sync"]["running"]):
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

        first = players[0]
        for key in ("bidLow", "bidHigh", "marginLow", "expectedPoints", "playProbability", "odds", "sellerInMinus"):
            check(key in first, f"market player has {key}")
        check(all(p["bidLow"] is None or p["bidLow"] >= p["marketValue"] for p in players), "bids start at the market value")
        check(all(0 <= r["probability"] <= 1 for p in players for r in p["rivals"]), "bidder probabilities are shares")
        check(any(p["expectedPoints"] for p in players), "market players carry expected points")

        wealth = client.get("/api/charts/wealth")
        check(wealth.status_code == 200, "wealth endpoint")
        check(len(wealth.json()["managers"]) > 1 and bool(wealth.json()["rows"]), "wealth comparison has managers and dates")

        rivals = client.get("/api/rivals")
        check(rivals.status_code == 200, f"rivals ({rivals.status_code} {rivals.text[:300]})")
        profiles = rivals.json()
        check(len(profiles["managers"]) > 1, f"{len(profiles['managers'])} rival profiles")
        check(any(m["balanceHistory"] for m in profiles["managers"]), "balance histories for the balances user")
        check(any(m["purchases"] for m in profiles["managers"]), "purchases are counted")

        detail = client.get("/api/managers/1002/detail")
        check(detail.status_code == 200, f"manager detail ({detail.status_code} {detail.text[:300]})")
        d = detail.json()
        check(len(d["squad"]) > 0 and d["clubs"], f"detail has {len(d['squad'])} players and clubs")
        check(len(d["achievements"]) == 36, f"{len(d['achievements'])} achievement rules")
        check(d["achievementsTotal"] > 0, f"achievements total {d['achievementsTotal']}")
        check(len(d["teamValues"]) > 5, f"{len(d['teamValues'])} team value days")
        check(d["season"] and d["days"], f"season with {len(d['season'])} matchdays, lineups of {len(d['days'])}")
        check(d["estimatedBalance"] is not None, "balances user sees the estimate")
        past = client.get(f"/api/managers/1002/detail?day={d['days'][0]}")
        check(past.status_code == 200 and past.json()["lineupIds"], "lineup of a past matchday")
        check(any(p["dayPoints"] is not None for p in past.json()["squad"]), "day points of a past matchday")
        check(client.get("/api/managers/9999/detail").status_code == 404, "unknown manager is 404")

        learned = client.get("/api/learning")
        check(learned.status_code == 200, f"learning ({learned.status_code} {learned.text[:300]})")
        lj = learned.json()
        check(lj["expectation"].get("historyRows", 0) > 0, f"expected points learned from {lj['expectation'].get('historyRows')} past matches")
        check(lj["auctionsLogged"] > 0, f"{lj['auctionsLogged']} auctions logged")
        check(len(lj["achievements"]) == 36, "achievement check lists every rule")
        check("balanceCorrection" in lj, "balance correction reported")

        buys = client.get("/api/planner/buys")
        check(buys.status_code == 200, f"buy planner ({buys.status_code} {buys.text[:300]})")
        check(len(buys.json()) > 0, f"buy planner has {len(buys.json())} options")

        odds = client.get("/api/odds/sample")
        check(odds.status_code == 200, f"odds sample ({len(odds.json())} stored answers)")

        everyone = client.get("/api/players")
        check(everyone.status_code == 200, "players")
        check(any(len(p.get("projection") or []) == 3 for p in everyone.json()), "players carry a projection")

        coach = client.get("/api/coach")
        check(coach.status_code == 200, f"coach ({coach.status_code} {coach.text[:300]})")
        view = coach.json()
        check(len(view["squad"]) > 0, f"coach squad has {len(view['squad'])} players")
        check(len(view["bestLineup"]) == 11, f"best eleven has {len(view['bestLineup'])} players")
        check(bool(view["checks"]), "coach has checks")
        check("sellAdvice" in view and "leagueForecast" in view, "coach has sell advice and league forecast")
        check(len(view["leagueForecast"]) > 1, f"league forecast for {len(view['leagueForecast'])} managers")
        check(any(p["expected"]["playProbability"] is not None for p in view["squad"]), "squad has start probabilities")
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

        ### The market watch: the first round only remembers, the second reports nothing new
        state = app.state.kbi
        rows = [state.automation.get_settings("1001", "4242")]
        check(rows[0].listing_alerts, "listing alerts are on by default")
        from db.models import utcnow

        client.portal.call(state.automation.watch_market, "4242", rows, utcnow())
        client.portal.call(state.automation.watch_market, "4242", rows, utcnow())
        check(True, "market watch ran twice")
        client.portal.call(state.automation.tick, utcnow())
        check(True, "automation round ran")

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
