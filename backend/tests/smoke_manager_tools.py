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
        check(
            len(wealth.json()["managers"]) > 1 and bool(wealth.json()["rows"]),
            "wealth comparison has managers and dates",
        )

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

        ### Autotrader: the dry run sends nothing to Kickbase, the live run bids and sells
        from sqlmodel import Session, select

        from db.models import League, TradeLog, TraderDebug

        current = client.get("/api/automation/settings").json()
        on = client.put("/api/automation/settings", json={**current, "trader": True, "traderLive": False})
        check(on.status_code == 200 and on.json()["trader"] and not on.json()["traderLive"], "trader on, dry run")
        with Session(state.engine) as s:
            league = s.get(League, "4242")
        kb_client = state.automation.client_for_user("1001")
        budget_before = client.portal.call(kb_client.own_budget, "4242").budget
        dry = client.portal.call(state.automation.trader.round, league, state.automation.get_settings("1001", "4242"), kb_client, utcnow())
        check(client.portal.call(kb_client.own_budget, "4242").budget == budget_before, f"dry run changed nothing ({len(dry)} planned)")
        print("    dry run:", [(a.kind, a.purpose, a.name, a.price, a.reason) for a in dry])
        with Session(state.engine) as s:
            planned = s.exec(select(TradeLog).where(TradeLog.status == "planned")).all()
        check(len(planned) == len(dry), f"{len(planned)} planned trades logged")

        ### With money to spend the plan buys for the eleven, within the free squad slots
        squad_now = client.portal.call(kb_client.manager_squad, "4242", "1001")
        market_now = client.portal.call(kb_client.market, "4242")
        rich, paper = state.automation.trader._plan(league, state.automation.get_settings("1001", "4242"), squad_now, 200_000_000, market_now, utcnow())
        print("    paper trades:", [(s.player_id, s.purpose, s.bid) for s in paper])
        check(len(paper) > 0 and all(s.bid >= s.market_value for s in paper), "rejected candidates are followed on paper")
        print("    plan with 200 Mio.:", [(a.kind, a.purpose, a.name, a.price, a.reason) for a in rich])
        slots = 18 - len(squad_now.players) - sum(1 for p in market_now.players if p.own_bid("1001") is not None)
        check(any(a.purpose == "lineup" for a in rich), "a lineup purchase is planned when money is there")
        check(sum(1 for a in rich if a.kind == "bid") <= max(slots, 0) + sum(1 for a in rich if a.kind == "sell"), "bids fit the free squad slots")

        ### Empty squad: the eleven first, one keeper at most, nothing for profit or the bench yet
        empty = squad_now.model_copy(update={"players": []})
        start, _ = state.automation.trader._plan(league, state.automation.get_settings("1001", "4242"), empty, 200_000_000, market_now, utcnow())
        positions = {p.id: p.position for p in market_now.players}
        print("    plan for an empty squad:", [(a.purpose, a.name, positions.get(a.player_id), a.price) for a in start])
        check(sum(1 for a in start if a.kind == "bid" and positions.get(a.player_id) == 1) <= 1, "one keeper at most")
        check(all(a.purpose == "lineup" for a in start if a.kind == "bid"), "an empty squad bids for the eleven only")

        open_before = sum(p.own_bid("1001") or 0 for p in market_now.players)
        client.put("/api/automation/settings", json={**current, "trader": True, "traderLive": True})
        live = client.portal.call(state.automation.trader.round, league, state.automation.get_settings("1001", "4242"), kb_client, utcnow())
        print("    live run:", [(a.kind, a.purpose, a.name, a.price, a.reason) for a in live])
        market_after = client.portal.call(kb_client.market, "4242")
        open_bids = {p.id: p.own_bid("1001") for p in market_after.players if p.own_bid("1001") is not None}
        check(
            all(open_bids.get(a.player_id) == a.price for a in live if a.kind == "bid"),
            f"every live bid is at Kickbase ({len(open_bids)} open own bids)",
        )
        new_bids = sum(a.price for a in live if a.kind == "bid")
        received = sum(a.price for a in live if a.kind == "sell")
        check(new_bids <= max(0, budget_before - open_before) + received, "the trader's bids fit the free budget")
        ### The live steps themselves: a bid at Kickbase and a sale, both in the log and the week
        from sync.trader import Action

        free_agent = next(p for p in market_after.players if p.seller is None and p.own_bid("1001") is None)
        bid = Action("bid", "profit", free_agent.id, free_agent.last_name, free_agent.market_value, free_agent.market_value, reason="test")
        client.portal.call(state.automation.trader._execute, league, "1001", kb_client, bid)
        placed = client.portal.call(kb_client.market, "4242")
        check(any(p.id == free_agent.id and p.own_bid("1001") == free_agent.market_value for p in placed.players), "live bid placed")
        bench = client.portal.call(kb_client.manager_squad, "4242", "1001").players[-1]
        sale = Action("sell", "room", bench.id, bench.last_name, bench.market_value, bench.market_value, reason="test")
        client.portal.call(state.automation.trader._execute, league, "1001", kb_client, sale)
        with Session(state.engine) as s:
            logged = s.exec(select(TradeLog).where(TradeLog.status.in_(["open", "sold"]))).all()
        check({r.kind for r in logged} == {"bid", "sell"}, "live bid and sale are logged")
        live = [*live, bid, sale]

        ### Unclear outcome: no answer from Kickbase leaves the entry `unknown`, the player blocked, and
        ### the next round settles it against Kickbase instead of sending it again
        from datetime import datetime, timedelta

        from kickbase import KickbaseError as KbError

        target = next(p for p in placed.players if p.seller is None and p.own_bid("1001") is None and p.id != free_agent.id)
        real_offer = kb_client.place_offer

        async def lost_answer(league_id, player_id, price):
            await real_offer(league_id, player_id, price) # Reaches Kickbase, but the answer is lost
            raise KbError("timeout")

        kb_client.place_offer = lost_answer
        lost = Action("bid", "lineup", target.id, target.last_name, target.market_value, target.market_value, reason="test")
        outcome = client.portal.call(state.automation.trader._execute, league, "1001", kb_client, lost)
        kb_client.place_offer = real_offer
        check(outcome == "unknown", f"a lost answer is unknown, not failed ({outcome})")
        squad_x = client.portal.call(kb_client.manager_squad, "4242", "1001")
        market_x = client.portal.call(kb_client.market, "4242")
        _, _ = state.automation.trader._plan(league, state.automation.get_settings("1001", "4242"), squad_x, 200_000_000, market_x, utcnow())
        with Session(state.engine) as s:
            debug = s.exec(select(TraderDebug).order_by(TraderDebug.id.desc())).first()
        check(target.id in {p["id"] for p in debug.data["pending"]} and all(a["player_id"] != target.id for a in debug.data["actions"]),
              "an unknown bid is not sent twice")
        state.automation.trader._settle(league, "1001", squad_x, market_x, utcnow())
        with Session(state.engine) as s:
            settled = s.exec(select(TradeLog).where(TradeLog.player_id == target.id, TradeLog.kind == "bid")).one()
        check(settled.status == "open", f"Kickbase shows the bid: settled as open ({settled.status})")

        ### A rate limit (HTTP 429) is a refusal: failed, not unknown, nothing sent twice
        async def rate_limited(league_id, player_id, price):
            raise KbError("too many requests", 429)

        kb_client.place_offer = rate_limited
        limited = Action("bid", "lineup", target.id, target.last_name, target.market_value, target.market_value, reason="test")
        check(client.portal.call(state.automation.trader._execute, league, "1001", kb_client, limited) == "failed", "HTTP 429 counts as failed")
        kb_client.place_offer = real_offer

        refused_bid = Action("bid", "lineup", "999999", "Niemand", 1_000_000, 1_000_000, reason="test")
        check(client.portal.call(state.automation.trader._execute, league, "1001", kb_client, refused_bid) == "failed", "a refused call is failed")

        ### A sale whose balance cannot be read afterwards is still a sale, with unknown proceeds (no 0 €)
        real_budget = kb_client.own_budget
        calls = {"n": 0}

        async def flaky_budget(league_id):
            calls["n"] += 1
            if calls["n"] > 1:
                raise KbError("timeout")
            return await real_budget(league_id)

        seller = client.portal.call(kb_client.manager_squad, "4242", "1001").players[-1]
        kb_client.own_budget = flaky_budget
        flaky = Action("sell", "room", seller.id, seller.last_name, seller.market_value, seller.market_value, reason="test", cost=1)
        check(client.portal.call(state.automation.trader._execute, league, "1001", kb_client, flaky) == "done", "the sale went through")
        kb_client.own_budget = real_budget
        with Session(state.engine) as s:
            sold = s.exec(select(TradeLog).where(TradeLog.player_id == seller.id, TradeLog.kind == "sell")).one()
        check(sold.status == "sold" and sold.profit is None and sold.details["received_known"] is False, f"unknown proceeds stay unknown {sold.details}")
        live = [*live, lost, flaky]

        ### In the repay phase with a negative balance: rescue sales only, no bid, starters kept.
        ### The repay phase starts after the last market value update (22:15 Berlin), and the demo deadline
        ### moves with the clock: a fixed "two hours before" was sometimes still the prepare phase
        from core import trader as core_trader

        coach_view = client.get("/api/coach").json()
        deadline_at = datetime.fromisoformat(coach_view["matchday"]["deadline"].replace("Z", "+00:00"))
        rescue_at = core_trader.repay_from(deadline_at) + timedelta(minutes=1)
        check(core_trader.phase(rescue_at, deadline_at) in ("repay", "final"), f"rescue check runs in the repay phase ({rescue_at})")
        rescue_plan, _ = state.automation.trader._plan(
            league, state.automation.get_settings("1001", "4242"), squad_x, -3_000_000, market_x, rescue_at
        )
        print("    rescue:", [(a.kind, a.purpose, a.name, a.price) for a in rescue_plan])
        check(rescue_plan and all(a.kind in ("sell", "withdraw") for a in rescue_plan), "negative balance before the deadline: no bids, rescue only")
        check(any(a.purpose == "rescue" for a in rescue_plan), "rescue sales planned")
        far_plan, _ = state.automation.trader._plan(
            league, state.automation.get_settings("1001", "4242"), squad_x, -3_000_000, market_x, deadline_at - timedelta(days=3)
        )
        check(not any(a.purpose == "rescue" for a in far_plan), "no rescue sales days before the deadline")

        ### Exit system: a profit position bought three days ago is judged every round, and an exit
        ### verdict on an unprotected player becomes one sale
        bench_player = next(c for c in squad_x.players[::-1])
        with Session(state.engine) as s:
            s.add(TradeLog(user_id="1001", league_id="4242", player_id=bench_player.id, kind="bid", purpose="profit", status="won",
                           price=bench_player.market_value * 3, paid=bench_player.market_value * 3, market_value=bench_player.market_value,
                           at=utcnow() - timedelta(days=3), resolved_at=utcnow() - timedelta(days=3)))
            s.commit()
        state.automation.trader._last_debug.clear()
        exit_plan, _ = state.automation.trader._plan(league, state.automation.get_settings("1001", "4242"), squad_x, 5_000_000, market_x, utcnow())
        with Session(state.engine) as s:
            debug = s.exec(select(TraderDebug).order_by(TraderDebug.id.desc())).first()
        verdict = debug.data["positions"].get(bench_player.id, {}).get("verdict")
        print("    position:", debug.data["positions"].get(bench_player.id), "plan:", [(a.kind, a.purpose, a.reason) for a in exit_plan])
        check(verdict is not None and debug.data["unrealized"] < 0, f"the position is judged ({verdict}), its book loss counted")
        exited = [a for a in exit_plan if a.purpose == "exit"]
        check((verdict in ("SPORT", "STOP", "TRAIL", "TURN", "TAKE", "TIME")) == (len(exited) == 1), "an exit verdict on a free player is one sale")
        check(debug.data["paused"] is (debug.data["unrealized"] + debug.data["week_profit"] <= -3_000_000), "book losses count for the stop-loss")
        ### E01.00: the logged liquidation is the one that limited the credit. Two sales today already
        ### (daily limit 3): it covers fewer sales than the whole day's limit
        from core import trader as core_trader

        team_value = sum(p["value"] for p in debug.data["squad"])
        check(debug.data["credit"] == core_trader.credit(5_000_000, team_value, debug.data["liquidation"]),
              f"the logged liquidation limited the credit ({debug.data['liquidation']:,}, credit {debug.data['credit']:,})")
        check(debug.data["liquidation"] <= debug.data["liquidation_full_day"],
              f"sales used today count ({debug.data['liquidation']:,} <= {debug.data['liquidation_full_day']:,})")

        ### Dry run entries use up no live limits and block no player
        with Session(state.engine) as s:
            s.add(TradeLog(user_id="1001", league_id="4242", player_id="dry", kind="sell", purpose="turn", status="planned", price=1, market_value=1))
            s.add(TradeLog(user_id="1001", league_id="4242", player_id="dry", kind="bid", purpose="profit", status="planned", price=1, market_value=1))
            s.commit()
        plan_after, _ = state.automation.trader._plan(league, state.automation.get_settings("1001", "4242"), squad_x, 200_000_000, market_x, utcnow())
        state.automation.trader._last_debug.clear() # Log this round even if nothing changed
        state.automation.trader._plan(league, state.automation.get_settings("1001", "4242"), squad_x, 200_000_000, market_x, utcnow())
        with Session(state.engine) as s:
            debug = s.exec(select(TraderDebug).order_by(TraderDebug.id.desc())).first()
            bids = s.exec(select(TradeLog).where(TradeLog.kind == "bid")).all()
        from core.analytics import MARKET_VALUE_TIMEZONE

        midnight = utcnow().astimezone(MARKET_VALUE_TIMEZONE).replace(hour=0, minute=0, second=0, microsecond=0)
        real_bids = sum(1 for r in bids if r.status not in ("planned", "failed") and r.at >= midnight)
        planned_now = sum(1 for a in [*debug.data["actions"], *debug.data["risk_blocked"]] if a["kind"] == "bid")
        dry_bids = sum(1 for r in bids if r.status == "planned")
        check(dry_bids > 0 and debug.data["bids_left"] + planned_now == 6 - real_bids,
              f"daily bids count real calls only ({real_bids} real, {dry_bids} dry run)")

        ### Shadow trades: a paper sale and a paper purchase of a Kickbase listing, both a few days old,
        ### are settled into results and teach the trader
        from datetime import timedelta

        from db.models import MarketValueHistory, ShadowTrade, Transfer

        listed_now = {p.id for p in client.portal.call(kb_client.market, "4242").players}
        with Session(state.engine) as s:
            traded = set(s.exec(select(Transfer.player_id)).all())
            quiet = [
                pid for pid, points in s.exec(select(MarketValueHistory.player_id, MarketValueHistory.points)).all()
                if pid not in listed_now and pid not in traded and len(points) > 30
            ][:2]
            old = utcnow() - timedelta(days=6)
            s.add(ShadowTrade(league_id="4242", user_id="1001", player_id=quiet[0], kind="sell", purpose="room", market_value=1_000_000, at=old))
            s.add(ShadowTrade(league_id="4242", user_id="1001", player_id=quiet[1], kind="buy", purpose="profit", bid=1_000_000,
                              market_value=1_000_000, forecast_gain=200_000, free_agent=True, at=old))
            s.commit()
        empty_market = client.portal.call(kb_client.market, "4242")
        state.automation.trader._settle_shadows(league, empty_market, utcnow())
        state.automation.trader._settle_shadows(league, empty_market, utcnow())
        with Session(state.engine) as s:
            shadows = {r.kind: r for r in s.exec(select(ShadowTrade).where(ShadowTrade.player_id.in_(quiet))).all()}
        check(shadows["sell"].status == "done" and shadows["sell"].result is not None, f"paper sale settled ({shadows['sell'].result})")
        check(shadows["buy"].status == "expired" and shadows["buy"].result is None,
              f"a listing gone without a transfer is no won paper auction ({shadows['buy'].status})")

        trader = client.get("/api/automation/trader")
        check(trader.status_code == 200, f"trader view ({trader.status_code} {trader.text[:300]})")
        tj = trader.json()
        check(len(tj["learned"]["extra"]) == 3 and tj["enabledOnServer"], "trader view has the learned bids per price class")
        with Session(state.engine) as s:
            rows = s.exec(select(TradeLog).where(TradeLog.user_id == "1001", TradeLog.league_id == "4242")).all()
        check(len(tj["trades"]) == min(len(rows), 40), f"trader view lists {len(tj['trades'])} trades")
        check(not any(w["profit"] for w in tj["weeks"]) or all(r.profit is not None for r in rows if r.kind == "sell" and r.status == "sold"),
              "unknown profits are not booked")
        check(tj["weeks"] and tj["weeks"][0]["sales"] >= 1 and tj["weeks"][0]["received"] > 0, f"week stats {tj['weeks'][:1]}")
        check(tj["learned"]["regretSamples"] >= 1, f"shadows taught the trader {tj['learned']}")
        check(len(tj["shadows"]) >= 2, f"shadow summary {tj['shadowSummary']}")
        check("forecastPaused" in tj["learned"] and "directionRate" in tj["learned"], "forecast quality in the view")
        opts = client.put("/api/automation/settings", json={**current, "traderOptions": {"minGain": 5, "maxCostPerPoint": 200000}})
        check(opts.status_code == 200 and opts.json()["traderOptions"]["minGain"] == 5, "trader options are stored")
        bad = client.put("/api/automation/settings", json={**current, "traderOptions": {"dailyBids": 1000}})
        check(bad.status_code == 422, f"out of range options are refused ({bad.status_code})")

        ### Export for an AI review, import of tuned values without a new build
        export = client.get("/api/automation/trader/export?days=7")
        ej = export.json()
        check(export.status_code == 200 and ej["rounds"] and "decision" in ej["rounds"][-1]["data"]["market"][0], "export holds the decisions of the rounds")
        tuned = {"options": {"min_gain": 4.5, "daily_bids": 999, "nope": 1}, "learned": {"swap_edge": 1, "extra": [0.2, 0.5, 2]}}
        refused = client.post("/api/automation/trader/import", json=tuned)
        check(refused.status_code == 403, f"without KBI_AUTOMATION__TRADER_ADMINS nobody changes the shared learning ({refused.status_code})")
        state.settings.automation.trader_admins = ["1001"]
        imported = client.post("/api/automation/trader/import", json=tuned)
        ij = imported.json()
        check(imported.status_code == 200, f"import ({imported.status_code} {imported.text[:200]})")
        check(ij["options"]["min_gain"] == 4.5 and ij["options"]["daily_bids"] == 30 and ij["ignored"] == ["options.nope"], f"options merged and clamped {ij}")
        check(ij["learned"]["swap_edge"] == 50_000 and ij["learned"]["extra"] == [0.2, 0.5, 1.0], f"learned values clamped {ij['learned']}")

        ### Dashboard: the latest round's state and the statistics
        dash = client.get("/api/automation/trader/dashboard")
        dj = dash.json()
        print("    dashboard:", {k: dj.get(k) for k in ("phase", "budget", "open_bids", "credit", "worst_case", "gaps_confirmed", "gaps_projected", "runtime_ms")})
        print("    stats:", dj.get("stats"))
        check(dash.status_code == 200 and dj["at"] and dj["gaps_confirmed"] is not None and dj["runtime_ms"] is not None, "dashboard from the latest round")
        check(isinstance(dj["candidates"], list) and all("decision" in c for c in dj["candidates"]), "candidates with their reason")
        check(dj["stats"]["unknown_profits"] >= 1 and dj["stats"]["sales"] >= dj["stats"]["unknown_profits"], "unknown profits counted apart")
        ### E01.04: every planning round logs the max bid next to the released money, the limits add up
        with Session(state.engine) as s:
            rounds = [r.data for r in s.exec(select(TraderDebug)).all() if not r.data.get("rescue")]
        mcs = [r.get("money_check") for r in rounds]
        check(mcs and all(mc and all(mc["gap"][p] == sum(mc["limits"][p].values()) for p in mc["released"]) for mc in mcs),
              f"max bid and released money in every round ({len(mcs)} rounds), the limits add up")
        check("money_check" in dj and (dj["money_check"] is None or dj["money_check"]["max_bid"] >= 0), "the dashboard shows the max bid check")

        ### Notifications: an eleven with gaps close to the matchday is pushed once per deadline
        from db.models import AutomationEvent

        notes_before = len(state.automation.trader._pushes)
        friday = utcnow() + timedelta(hours=10)
        state.automation.trader._notify("4242", "1001", {"gaps_confirmed": 2, "gaps_projected": 1}, "prepare", friday, utcnow())
        state.automation.trader._notify("4242", "1001", {"gaps_confirmed": 2, "gaps_projected": 1}, "prepare", friday, utcnow())
        state.automation.trader._notify("4242", "1001", {"gaps_confirmed": 2}, "normal", friday, utcnow())
        with Session(state.engine) as s:
            gap_events = s.exec(select(AutomationEvent).where(AutomationEvent.key.like("trader-gaps:%"))).all()
        check(len(gap_events) == 1 and len(state.automation.trader._pushes) == notes_before + 1, "gap warning once, only close to the matchday")
        state.automation.trader._pushes.clear()

        ### Paper trades of another member's trader stay his: not in this user's view or export
        with Session(state.engine) as s:
            s.add(ShadowTrade(league_id="4242", user_id="9999", player_id="secret", kind="buy", purpose="profit", bid=1, market_value=1))
            s.commit()
        mine = client.get("/api/automation/trader/export?days=1").json()
        trader_view = client.get("/api/automation/trader").json()
        check(all(sh["player_id"] != "secret" for sh in mine["shadows"]) and all(sh["playerId"] != "secret" for sh in trader_view["shadows"]),
              "another user's paper trades are not shown")

        ### Strategy profiles and the backtest on the league's real auctions
        profiles = client.get("/api/automation/trader/profiles").json()
        check(set(profiles) == {"conservative", "balanced", "aggressive"} and profiles["conservative"]["profitShare"] == 30, f"profiles {profiles['conservative']}")
        import time as _time

        started = _time.time()
        bt = client.get("/api/automation/trader/backtest?folds=3")
        took = _time.time() - started
        bj = bt.json()
        print(f"    backtest ({took:.1f} s):", bj["data"], bj["windows"])
        for res in bj["results"]:
            print("     ", res)
        check(bt.status_code == 200 and [r["strategy"] for r in bj["results"]] == ["none", "reference", "conservative", "balanced", "aggressive"],
              f"backtest compares five strategies ({bt.status_code})")
        none = bj["results"][0]
        check(none["net_profit"] == 0 and none["bids"] == 0, "no trading makes nothing")
        check(all(r["won"] + r["lost"] == r["bids"] and r["trades"] <= r["won"] for r in bj["results"]), "consistent counts")

        ### League learning: the export shows the base, the league's own and the blend; a reset needs
        ### an admin and logs the old values
        ex2 = client.get("/api/automation/trader/export?days=1").json()
        check({"learned", "learned_league", "learned_effective"} <= set(ex2) and ex2["learned"]["version"] == 2, "base, league and blend exported")
        reset = client.post("/api/automation/trader/reset?scope=league")
        check(reset.status_code == 200 and "before" in reset.json(), f"league learning reset ({reset.status_code})")
        state.settings.automation.trader_admins = []
        check(client.post("/api/automation/trader/reset?scope=global").status_code == 403, "reset only by admins")
        check(client.post("/api/automation/trader/reset?scope=all").status_code == 422, "unknown scope refused")

        ### Concurrent learning updates: none is lost (two fields written by two threads at once)
        import threading

        trader_service = state.automation.trader

        def writer(field: str, value: int) -> None:
            for _ in range(15):
                trader_service.import_tuning("1001", "4242", None, {field: value})

        threads = [threading.Thread(target=writer, args=("min_margin", 222_000)), threading.Thread(target=writer, args=("swap_edge", 333_000))]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        final = client.get("/api/automation/trader/export?days=1").json()["learned"]
        check(final["min_margin"] == 222_000 and final["swap_edge"] == 333_000, f"both concurrent updates kept {final['min_margin']} {final['swap_edge']}")
        client.put("/api/automation/settings", json={**current, "trader": False})

        events = client.get("/api/automation/events")
        check(events.status_code == 200, f"events ({len(events.json())})")

        quality = client.get("/api/automation/forecast")
        check(quality.status_code == 200, f"forecast quality {quality.json()}")

        key = client.get("/api/push/key").json()
        check(bool(key.get("publicKey")), "push key is generated")
        sub = client.post(
            "/api/push/subscribe",
            json={"endpoint": "https://fcm.googleapis.com/fake-test-subscription", "p256dh": "x" * 20, "auth": "y" * 8},
        )
        check(sub.status_code == 200 and sub.json()["subscribed"] == 1, "push subscription stored")

        sell_id = view["squad"][-1]["id"]
        before = view["budget"]
        sold = client.post(f"/api/squad/{sell_id}/sell")
        check(sold.status_code == 200, f"instant sale ({sold.status_code} {sold.text[:300]})")
        check(sold.json()["budget"] > before, "budget rose after the sale")
        after = client.get("/api/coach").json()
        check(sell_id not in {p["id"] for p in after["squad"]}, "sold player left the squad")

        ### E01.00: the daily sale limit used up, the credit has no liquidation left, and the log says so
        ### (it showed the whole day's liquidation before)
        with Session(state.engine) as s:
            for n in range(5):
                s.add(TradeLog(user_id="1001", league_id="4242", player_id=f"liq{n}", kind="sell", purpose="room", status="sold",
                               price=1, market_value=1))
            s.commit()
        state.automation.trader._last_debug.clear()
        squad_l = client.portal.call(kb_client.manager_squad, "4242", "1001")
        market_l = client.portal.call(kb_client.market, "4242")
        state.automation.trader._plan(league, state.automation.get_settings("1001", "4242"), squad_l, 5_000_000, market_l, utcnow())
        with Session(state.engine) as s:
            debug = s.exec(select(TraderDebug).order_by(TraderDebug.id.desc())).first()
        check(debug.data["liquidation"] == 0 and debug.data["credit"] == 0,
              f"no sales left today: no liquidation, no credit ({debug.data['liquidation']}, {debug.data['credit']})")
        check(debug.data["liquidation_full_day"] > 0, f"the whole day's liquidation is logged for comparison ({debug.data['liquidation_full_day']:,})")

    print("\nAll manager tool checks passed.")


if __name__ == "__main__":
    main()
