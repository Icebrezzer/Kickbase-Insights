"""Offline regressions for the code audit. All HTTP requests use MockTransport."""
from __future__ import annotations

import asyncio
import sys
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from check_trader_safety import A, ctx, p
from sqlmodel import Session

from api.routes import AppState
from auth.accounts import LoginError, LoginRateLimiter
from core import analytics, coach, risk
from core.config import Settings
from db import create_db_engine, init_db
from db.models import (
    AutomationEvent,
    Fixture,
    League,
    LeagueSeason,
    Player,
    Team,
    TradeLog,
    UserAutomation,
    UserLeague,
    utcnow,
)
from kickbase import models as kb
from kickbase.client import KickbaseAuthError, KickbaseClient, KickbaseError, KickbaseHttp
from sync.odds import OddsService
from sync.push import validate_endpoint
from sync.service import FetchResult, SyncService
from sync.trader import Action, TraderService


class HttpTests(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_login_response_is_a_controlled_error(self):
        http = KickbaseHttp(transport=httpx.MockTransport(lambda _: httpx.Response(200, text="broken")))
        try:
            with self.assertRaises(KickbaseError):
                await http.login("demo", "demo")
        finally:
            await http.aclose()

    async def test_missing_squad_is_not_an_empty_squad(self):
        async with KickbaseClient(token="test", transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={})
        )) as client:
            with self.assertRaises(KickbaseError):
                await client.manager_squad("1", "2")
            with self.assertRaises(KickbaseError):
                await client.market("1")

    async def test_explicit_empty_squad_is_valid(self):
        async with KickbaseClient(token="test", transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"it": []})
        )) as client:
            self.assertEqual((await client.manager_squad("1", "2")).players, [])

    async def test_write_401_never_retries_or_relogs(self):
        calls = []

        def handle(request):
            calls.append(request)
            return httpx.Response(401)

        async with KickbaseClient(
            email="test", password="test", token="test",
            token_expiry=datetime.now(UTC) + timedelta(hours=1),
            transport=httpx.MockTransport(handle),
        ) as client:
            client.login = AsyncMock()
            with self.assertRaises(KickbaseAuthError):
                await client.place_offer("1", "2", 10000)
            self.assertEqual(len(calls), 1)
            client.login.assert_not_awaited()

    async def test_malformed_write_response_is_unknown_and_not_retried(self):
        calls = []

        def handle(request):
            calls.append(request)
            return httpx.Response(200, text="not JSON")

        async with KickbaseClient(token="test", transport=httpx.MockTransport(handle)) as client:
            with self.assertRaises(KickbaseError) as raised:
                await client.sell_to_kickbase("1", "2")
            self.assertIsNone(raised.exception.status_code)
            self.assertEqual(len(calls), 1)

    async def test_read_can_refresh_revoked_token(self):
        calls = []

        def handle(request):
            calls.append(request)
            return httpx.Response(401 if len(calls) == 1 else 200, json={"ok": True})

        async with KickbaseClient(
            email="test", password="test", token="test",
            token_expiry=datetime.now(UTC) + timedelta(hours=1),
            transport=httpx.MockTransport(handle),
        ) as client:
            async def relogin():
                client._token = "renewed"
            client.login = AsyncMock(side_effect=relogin)
            self.assertEqual(await client.request("GET", "/test"), {"ok": True})
            self.assertEqual(len(calls), 2)
            client.login.assert_awaited_once()


class RiskTests(unittest.TestCase):
    def test_uncertain_write_blocks_new_exposure_but_allows_withdrawal(self):
        context = ctx(unconfirmed=True, open_bids={"old": 10000}, trader_bids={"old"})
        self.assertEqual(risk.validate([
            A("bid", "lineup", "new", 10000), A("sell", "room", "f3", 10000),
            A("withdraw", "lineup", "old", 10000),
        ], context), [risk.UNCONFIRMED_ACTION, risk.UNCONFIRMED_ACTION, None])

    def test_withdraw_releases_club_slot(self):
        target = p("new", 3, 30, team_id="club")
        context = ctx(
            listings={"new": target}, open_bids={"old": 5_000_000}, trader_bids={"old"},
            club_of={"old": "club", "new": "club"}, max_club=1,
        )
        self.assertEqual(risk.validate([
            A("withdraw", "lineup", "old", 5_000_000),
            A("bid", "lineup", "new", 5_000_000),
        ], context), [None, None])

    def test_unknown_action_fails_closed(self):
        self.assertEqual(risk.validate([A("typo", "lineup", "1", 1)], ctx()), [risk.ACTION_INVALID])


class PushTests(unittest.TestCase):
    def test_rejects_internal_and_disguised_hosts(self):
        for endpoint in (
            "http://127.0.0.1/internal", "https://127.0.0.1/internal", "https://[::1]/internal",
            "https://fcm.googleapis.com.evil.test/push", "https://fcm.googleapis.com@localhost/push",
            "https://fcm.googleapis.com:444/push", "https://evil.test/push",
            "https://fcm.googleapis.com/push#fragment", "https://fcm.googleapis.com\\@localhost/push",
        ):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                validate_endpoint(endpoint)

    def test_accepts_supported_providers(self):
        for host in ("fcm.googleapis.com", "updates.push.services.mozilla.com", "web.push.apple.com"):
            endpoint = f"https://{host}/test"
            self.assertEqual(validate_endpoint(endpoint), endpoint)


class DataTests(unittest.TestCase):
    def test_deltas_use_calendar_days_not_entry_count(self):
        self.assertEqual(analytics.market_value_deltas([[1, 100], [2, 110], [4, 160]])["today"], None)
        self.assertEqual(analytics.market_value_deltas([[1, 100], [2, 110], [8, 190]])["seven_days"], 90)
        self.assertEqual(analytics.market_value_deltas([])["today"], None)

    def test_automation_requires_membership_and_allowed_league(self):
        from sync.automation import AutomationService

        engine = create_db_engine("sqlite://")
        try:
            init_db(engine)
            with Session(engine) as session:
                for lid in ("allowed", "blocked", "removed"):
                    session.add(League(id=lid, name=lid))
                    session.add(UserAutomation(user_id="u", league_id=lid, trader=True))
                session.add_all([UserLeague(user_id="u", league_id=lid) for lid in ("allowed", "blocked")])
                session.commit()
            service = SimpleNamespace(engine=engine, settings=Settings(auth={"blocked_leagues": ["blocked"]}, _env_file=None))
            self.assertEqual([row.league_id for row in AutomationService._enabled(service)], ["allowed"])
        finally:
            engine.dispose()

    def test_only_api_failures_trip_error_pause(self):
        engine = create_db_engine("sqlite://")
        try:
            init_db(engine)
            trader = TraderService(SimpleNamespace(engine=engine, settings=None, _has_key=lambda _: True))
            with Session(engine) as session:
                for _ in range(3):
                    session.add(AutomationEvent(user_id="u", league_id="l", kind="trader", ok=False, message="risk warning"))
                session.commit()
                self.assertIsNone(trader._error_pause("l", "u", utcnow()))
                for _ in range(3):
                    session.add(AutomationEvent(user_id="u", league_id="l", kind="trader", ok=False, message="API failed", details={"api_error": True}))
                session.commit()
            self.assertIsNotNone(trader._error_pause("l", "u", utcnow()))
        finally:
            engine.dispose()

    def test_rescue_withdrawal_is_not_planned_twice(self):
        engine = create_db_engine("sqlite://")
        try:
            init_db(engine)
            now = utcnow()
            league = League(id="league", name="Test")
            with Session(engine) as session:
                session.add(Fixture(id="game", day=1, kickoff=now + timedelta(minutes=30)))
                session.add(TradeLog(user_id="user", league_id="league", player_id="target", kind="bid",
                                     purpose="lineup", status="open", price=100_000, market_value=100_000))
                session.commit()
            automation = SimpleNamespace(engine=engine, settings=Settings(_env_file=None), model=coach.ForecastModel())
            trader = TraderService(automation)
            trader._notify = Mock()
            trader._log_debug = Mock()
            market = kb.Market(players=[kb.MarketPlayer(
                id="target", position=3, market_value=100_000, expires_in=600,
                offers=[kb.MarketOffer(user_id="user", price=100_000, id="offer")],
            )])
            with patch("api.insights.Insights") as insights:
                insights.return_value.market.return_value = []
                insights.return_value.winning_shares.return_value = []
                actions, _ = trader._plan(league, UserAutomation(user_id="user", league_id="league", trader=True),
                                          kb.ManagerSquad(), 50_000, market, now)
            self.assertEqual([(a.kind, a.player_id) for a in actions], [("withdraw", "target")])
        finally:
            engine.dispose()

    def test_purchase_reconstruction_is_reused_per_response(self):
        from api.insights import Insights

        insight = Insights(Mock(), League(id="1", name="Test"))
        insight._transfer_records = Mock(return_value=[])
        insight._histories = Mock(return_value={})
        self.assertEqual(insight._purchases(), [])
        self.assertEqual(insight.winning_shares(), [])
        insight._transfer_records.assert_called_once()
        insight._histories.assert_called_once()

    def test_forecast_requires_consecutive_days(self):
        points = [[day, 1_000_000 + day * 10_000] for day in range(12)]
        self.assertIsNotNone(coach.forecast(points))
        self.assertIsNone(coach.forecast(points[:8] + points[9:]))
        self.assertIsNone(coach.forecast(points, horizon=0))

    def test_sync_preserves_other_competitions(self):
        engine = create_db_engine("sqlite://")
        try:
            init_db(engine)
            with Session(engine) as session:
                session.add_all([
                    Team(id="a", name="A", competition_id=1), Team(id="b", name="B", competition_id=2),
                    Player(id="1", team_id="a", active=True), Player(id="2", team_id="b", active=True),
                ])
                session.commit()
            fetched = FetchResult(
                league=kb.LeagueInfo(id="league", name="Test"), competition_id=1, user_id="user",
                table=kb.CompetitionTable(), matchdays=kb.Matchdays(), overview=kb.LeagueOverview(start_budget=0),
                market=kb.Market(), budget=0, profiles=[], squads=[], dashboards={}, battles=[],
                rankings={}, current_day=None, manager_transfers={}, details={}, histories={},
            )
            SyncService(Settings(_env_file=None), engine, None)._store(fetched)
            with Session(engine) as session:
                self.assertFalse(session.get(Player, "1").active)
                self.assertTrue(session.get(Player, "2").active)
                self.assertEqual(session.get(LeagueSeason, "league").start_money, 0)
        finally:
            engine.dispose()


class ExpectationLearningTests(unittest.TestCase):
    """Expected points are learned per competition, from its own players only, without counting a
    logged match twice and without today's table for past matches."""

    def test_competitions_learn_apart(self):
        from api.context import learned_weights
        from db.models import ExpectationLog, ModelState, PlayerForm
        from sync.learning import LearningService

        engine = create_db_engine("sqlite://")
        try:
            init_db(engine)
            with Session(engine) as session:
                for cid, team in ((1, "a"), (2, "b")):
                    session.add(Team(id=team, name=team, competition_id=cid, placement=1))
                    for n in range(40):
                        pid = f"{team}{n}"
                        session.add(Player(id=pid, team_id=team, active=True))
                        ### Competition 1 scores 10x what competition 2 scores
                        points = 100 if cid == 1 else 10
                        session.add(PlayerForm(player_id=pid, matches=[[d, points + (n + d) % 7, 90, None] for d in range(1, 13)]))
                session.add(ExpectationLog(competition_id=1, day=12, player_id="a0", form=1, average=1, chance=1, actual=5))
                session.commit()
            service = LearningService.__new__(LearningService)
            service.engine = engine
            service.fit_expectations(1, force=True)
            service.fit_expectations(2, force=True)
            with Session(engine) as session:
                one, two = session.get(ModelState, "expectation:1"), session.get(ModelState, "expectation:2")
                self.assertIsNotNone(one)
                self.assertIsNotNone(two)
                self.assertIsNone(session.get(ModelState, "expectation"), "no shared key any more")
                ### 40 players x 9 rebuilt matches each, the logged match of a0 not rebuilt again
                self.assertEqual(one.data["history_rows"], 40 * 9 - 1)
                self.assertEqual(two.data["history_rows"], 40 * 9, "only the own competition's players")
                self.assertEqual(learned_weights(session, 2).rows, two.data["rows"])
        finally:
            engine.dispose()

    def test_rebuilt_rows_use_no_table_of_today(self):
        from core.learning import history_rows

        rows = history_rows([[d, 50, 90, None] for d in range(1, 8)], {d: ("x", True) for d in range(1, 8)}, {"x": 18})
        self.assertTrue(rows and all(r.table == 0.0 for r in rows))
        self.assertEqual(len(history_rows([[d, 50, 90, None] for d in range(1, 8)], {}, {}, skip_days={5, 6})), len(rows) - 2)


class DemoDatabaseTests(unittest.TestCase):
    def test_demo_never_uses_a_configured_database(self):
        from api.app import database_url

        folder = Path("/tmp/kbi-demo-test")
        for database in ({"url": "postgresql+psycopg://u:p@prod/kickbase"}, {"host": "postgres"}, {}):
            settings = Settings(_env_file=None, demo=True, data_dir=folder, database=database)
            self.assertEqual(database_url(settings), f"sqlite:///{(folder / 'demo.db').as_posix()}", database)
        real = Settings(_env_file=None, demo=False, data_dir=folder, database={"url": "postgresql+psycopg://u:p@prod/kickbase"})
        self.assertEqual(database_url(real), "postgresql+psycopg://u:p@prod/kickbase", "without demo the configured one")


class ReconcileTests(unittest.TestCase):
    """Unclear calls are closed only on positive evidence, never just because time passed."""

    def _settle(self, entries, market_players, squad_players, transfers=()):
        engine = create_db_engine("sqlite://")
        init_db(engine)
        with Session(engine) as session:
            session.add_all(entries)
            session.add_all(transfers)
            session.commit()
        trader = TraderService(SimpleNamespace(engine=engine, settings=None))
        trader._settle(League(id="l", name="L"), "u", kb.ManagerSquad(players=squad_players), kb.Market(players=market_players), utcnow())
        with Session(engine) as session:
            from sqlmodel import select
            result = {r.player_id: r.status for r in session.exec(select(TradeLog)).all()}
        engine.dispose()
        return result

    def _entry(self, pid, kind="bid", minutes=20, status="unknown"):
        return TradeLog(user_id="u", league_id="l", player_id=pid, kind=kind, purpose="lineup", status=status,
                        price=1_000_000, market_value=1_000_000, at=utcnow() - timedelta(minutes=minutes))

    def test_gone_listing_without_transfer_stays_unclear(self):
        status = self._settle([self._entry("gone")], [], [])
        self.assertEqual(status["gone"], "unknown", "the bid may have been placed: no early 'failed'")

    def test_listing_without_own_bid_fails(self):
        listing = kb.MarketPlayer(id="still", market_value=1_000_000)
        self.assertEqual(self._settle([self._entry("still")], [listing], [])["still"], "failed")

    def test_recent_unclear_bid_waits(self):
        listing = kb.MarketPlayer(id="fresh", market_value=1_000_000)
        self.assertEqual(self._settle([self._entry("fresh", minutes=2)], [listing], [])["fresh"], "unknown")

    def test_gone_listing_with_a_transfer_is_settled_from_it(self):
        from db.models import Transfer

        transfer = Transfer(id="t1", league_id="l", player_id="won", date=utcnow() - timedelta(minutes=5), price=1_100_000,
                            buyer_id="other", seller_id=None)
        self.assertEqual(self._settle([self._entry("won")], [], [], [transfer])["won"], "lost")

    def test_unclear_bid_gives_up_after_two_days(self):
        self.assertEqual(self._settle([self._entry("old", minutes=3 * 24 * 60)], [], [])["old"], "expired")

    def test_unclear_sale_of_a_player_still_owned_fails_only_after_the_wait(self):
        owned = kb.SquadPlayer(id="kept", market_value=1_000_000)
        self.assertEqual(self._settle([self._entry("kept", kind="sell", minutes=2)], [], [owned])["kept"], "unknown")
        self.assertEqual(self._settle([self._entry("kept", kind="sell", minutes=20)], [], [owned])["kept"], "failed")


class ExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_confirmed_sale_survives_failed_balance_read(self):
        trader = TraderService(SimpleNamespace(engine=None, settings=None, record=Mock()))
        trader._log_intent = Mock(return_value=1)
        trader._finish_sale = Mock()
        trader._push = AsyncMock()
        client = SimpleNamespace(
            own_budget=AsyncMock(side_effect=[SimpleNamespace(budget=0), KickbaseAuthError("expired")]),
            sell_to_kickbase=AsyncMock(),
        )
        action = Action("sell", "rescue", "p", "P", 10000, 10000)
        league = League(id="l", name="L")
        self.assertEqual(await trader._execute(league, "u", client, action), "done")
        trader._finish_sale.assert_called_once_with(league, "u", 1, action, None)
        client.sell_to_kickbase.assert_awaited_once()

    async def test_manual_bid_waits_for_automation_lock(self):
        from api.routes import place_bid
        from api.schemas import BidIn

        lock = asyncio.Lock()
        client = SimpleNamespace(place_offer=AsyncMock())
        state = AppState(
            settings=None, engine=None, live=None, scheduler=None,
            automation=SimpleNamespace(_lock=lambda *_: lock),
            accounts=SimpleNamespace(client_for_viewer=lambda _: client),
            sync=SimpleNamespace(refresh_personal=AsyncMock()),
            cache={}, cache_lock=threading.Lock(), cache_generation=0,
        )
        await lock.acquire()
        task = asyncio.create_task(place_bid(state, "league", SimpleNamespace(user_id="user"), "1", BidIn(price=10000)))
        await asyncio.sleep(0)
        client.place_offer.assert_not_awaited()
        lock.release()
        result = await task
        self.assertEqual(result.own_bid, 10000)
        client.place_offer.assert_awaited_once()

    async def test_revalidation_rejects_changed_plan_and_unknown_budget(self):
        trader = TraderService(SimpleNamespace(engine=None, settings=None))
        trader._saved_lineup = AsyncMock(return_value=["1"])
        trader._plan = Mock(return_value=([], []))
        client = SimpleNamespace(
            manager_squad=AsyncMock(return_value="squad"), market=AsyncMock(return_value="market"),
            own_budget=AsyncMock(return_value=SimpleNamespace(budget=100)),
        )
        league, row = SimpleNamespace(id="1"), SimpleNamespace(user_id="2")
        action = Action("bid", "lineup", "3", "Test", 10000, 10000)
        self.assertFalse(await trader._revalidate(league, row, client, action))
        trader._plan.return_value = ([action], [])
        self.assertTrue(await trader._revalidate(league, row, client, action))
        trader._plan.return_value = ([Action("withdraw", "lineup", "old", "Old", 10000, 10000), action], [])
        self.assertFalse(await trader._revalidate(league, row, client, action))
        client.own_budget.return_value.budget = None
        trader._plan.reset_mock()
        self.assertFalse(await trader._revalidate(league, row, client, action))
        trader._plan.assert_not_called()

    async def test_manual_bid_change_prevents_withdrawal(self):
        trader = TraderService(SimpleNamespace(engine=None, settings=None))
        listing = SimpleNamespace(id="3", own_offer_id=lambda _: "offer", own_bid=lambda _: 20000)
        client = SimpleNamespace(market=AsyncMock(return_value=SimpleNamespace(players=[listing])),
                                 withdraw_offer=AsyncMock())
        result = await trader._withdraw(SimpleNamespace(id="1"), "2", client,
                                        Action("withdraw", "lineup", "3", "Test", 10000, 10000))
        self.assertEqual(result, "skipped")
        client.withdraw_offer.assert_not_awaited()


class CacheTests(unittest.TestCase):
    def test_invalidation_during_build_does_not_restore_stale_data(self):
        from api.routes import cached, forget_private

        state = AppState(settings=None, engine=None, accounts=None, sync=None, live=None, scheduler=None)
        league = League(id="league", name="Test")
        viewer = SimpleNamespace(user_id="user")
        started, release = threading.Event(), threading.Event()

        def build():
            started.set()
            self.assertTrue(release.wait(3))
            return "old"

        with ThreadPoolExecutor(max_workers=1) as pool:
            result = pool.submit(cached, state, league, ("budget",), build, viewer)
            self.assertTrue(started.wait(3))
            forget_private(state, league.id, viewer)
            release.set()
            self.assertEqual(result.result(timeout=3), "old")
        self.assertEqual(state.cache, {})
        self.assertEqual(cached(state, league, ("budget",), lambda: "new", viewer), "new")


class LoginTests(unittest.TestCase):
    def test_pending_attempts_count_and_release_on_cancellation(self):
        limiter = LoginRateLimiter(1)
        with limiter.attempt("mail", "ip"):
            with self.assertRaises(LoginError) as raised, limiter.attempt("mail", "ip"):
                self.fail("Concurrent attempt admitted")
            self.assertEqual(raised.exception.status_code, 429)
        self.assertFalse(limiter.blocked("mail", "ip"))
        with self.assertRaises(RuntimeError), limiter.attempt("mail", "ip"):
            raise RuntimeError("cancelled")
        self.assertEqual(limiter._pending, {})

    def test_old_rate_limit_keys_are_pruned(self):
        limiter = LoginRateLimiter(1)
        for i in range(20):
            limiter.record_failure(str(i), "ip")
        with patch("auth.accounts.utcnow", return_value=utcnow() + timedelta(minutes=16)):
            self.assertFalse(limiter.blocked("new", "new"))
        self.assertEqual(set(limiter._failures), {"mail:new", "ip:new"})


class OddsTests(unittest.IsolatedAsyncioTestCase):
    async def test_odds_require_both_teams_valid_time_and_finite_prices(self):
        engine = create_db_engine("sqlite://")
        try:
            init_db(engine)
            now = utcnow()
            with Session(engine) as session:
                session.add_all([Team(id="h", name="Bayern Munich"), Team(id="a", name="Dortmund")])
                session.commit()
            fixture = Fixture(id="f", day=1, kickoff=now, team1_id="h", team2_id="a")
            service = OddsService(Settings(_env_file=None), engine)
            outcomes = [{"name": "Bayern Munich", "price": 2}, {"name": "Dortmund", "price": 3}, {"name": "Draw", "price": 4}]
            event = {"id": "event", "commence_time": now.isoformat(), "home_team": "Bayern Munich", "away_team": "Dortmund",
                     "bookmakers": [{"markets": [{"key": "h2h", "outcomes": outcomes}]}]}
            response = Mock()
            http = AsyncMock()
            http.get.return_value = response
            with patch("sync.odds.httpx.AsyncClient") as factory:
                factory.return_value.__aenter__.return_value = http
                response.json.return_value = [event]
                self.assertEqual((await service._odds_api("secret", 1, [fixture]))["f"][0], (2, 4, 3))
                for bad in ({**event, "away_team": "Hamburg"}, {**event, "commence_time": now.replace(tzinfo=None).isoformat()}, {**event, "bookmakers": None}):
                    response.json.return_value = [bad]
                    self.assertEqual(await service._odds_api("secret", 1, [fixture]), {})
                response.json.return_value = [event]
                outcomes[0]["price"] = "Infinity"
                self.assertEqual(await service._odds_api("secret", 1, [fixture]), {})
                request = httpx.Request("GET", "https://api.the-odds-api.com?apiKey=secret")
                http.get.side_effect = httpx.HTTPStatusError("URL contains secret", request=request, response=httpx.Response(403))
                with self.assertLogs("sync.odds", level="WARNING") as logs:
                    self.assertEqual(await service._odds_api("secret", 1, [fixture]), {})
                self.assertNotIn("secret", " ".join(logs.output))
        finally:
            engine.dispose()

    def test_stale_odds_do_not_look_fresh(self):
        """A refresh without odds (outage, no data) keeps the old values with their old age; after
        ODDS_MAX_AGE they are left out, and fresh odds count again."""
        from api.context import ODDS_MAX_AGE, load_context
        from db.models import MatchOdds

        engine = create_db_engine("sqlite://")
        try:
            init_db(engine)
            now = utcnow()
            fixture = Fixture(id="f", competition_id=1, day=5, kickoff=now + timedelta(days=4), team1_id="h", team2_id="a")
            with Session(engine) as session:
                session.add(fixture)
                session.commit()
                session.refresh(fixture)
                session.expunge(fixture)
            service = OddsService(Settings(_env_file=None), engine)

            def odds(at):
                with Session(engine) as session:
                    return load_context(session, 1, [], at).odds

            service._store([fixture], {"f": ((2.0, 3.5, 4.0), "kickbase", {})}, {})
            self.assertEqual(odds(now), {"f": (2.0, 3.5, 4.0)})
            with Session(engine) as session:
                stored = session.get(MatchOdds, "f").updated_at
            ### Outage and missing data: the old odds stay, but do not become younger
            service._store([fixture], {}, {"f": None})
            service._store([fixture], {}, {"f": {"empty": True}})
            with Session(engine) as session:
                row = session.get(MatchOdds, "f")
                self.assertEqual(row.updated_at, stored)
                self.assertEqual(row.raw, {"empty": True})
            later = now + ODDS_MAX_AGE + timedelta(hours=1)
            self.assertEqual(odds(later), {}, "stale odds are not used")
            ### Recovery: fresh odds count again
            with patch("sync.odds.utcnow", return_value=later):
                service._store([fixture], {"f": ((1.8, 3.6, 4.4), "kickbase", {})}, {})
            self.assertEqual(odds(later), {"f": (1.8, 3.6, 4.4)})
        finally:
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
