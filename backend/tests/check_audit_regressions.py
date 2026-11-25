"""Offline regressions for the code audit. All HTTP requests use MockTransport."""
from __future__ import annotations

import sys
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from check_trader_safety import A, ctx, p
from sqlmodel import Session

from core import coach, risk
from core.config import Settings
from db import create_db_engine, init_db
from db.models import Fixture, League, Player, Team, TradeLog, UserAutomation, utcnow
from kickbase import models as kb
from kickbase.client import KickbaseAuthError, KickbaseClient, KickbaseError
from sync.push import validate_endpoint
from sync.service import FetchResult, SyncService
from sync.trader import Action, TraderService


class HttpTests(unittest.IsolatedAsyncioTestCase):
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
                table=kb.CompetitionTable(), matchdays=kb.Matchdays(), overview=kb.LeagueOverview(),
                market=kb.Market(), budget=0, profiles=[], squads=[], dashboards={}, battles=[],
                rankings={}, current_day=None, manager_transfers={}, details={}, histories={},
            )
            SyncService(Settings(_env_file=None), engine, None)._store(fetched)
            with Session(engine) as session:
                self.assertFalse(session.get(Player, "1").active)
                self.assertTrue(session.get(Player, "2").active)
        finally:
            engine.dispose()


class ExecutionTests(unittest.IsolatedAsyncioTestCase):
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


if __name__ == "__main__":
    unittest.main()
