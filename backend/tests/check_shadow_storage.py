"""Offline end-to-end checks through planning persistence, local settlement, reporting and archive."""

import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

from sqlmodel import Session, select

from core import analytics
from core.trader import Options
from db import create_db_engine, init_db
from db.models import (
    DecisionSnapshot,
    MarketValueHistory,
    ShadowAnalysis,
    ShadowDaily,
    TradeLog,
    Transfer,
    UserAutomation,
    utcnow,
)
from sync.shadow_analysis import settle_due
from sync.shadow_report import shadow_report
from sync.shadow_retention import archive_batch
from sync.trader import TraderService


class ShadowStorage(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.url = f"sqlite:///{Path(self.folder.name) / 'demo.db'}"
        self.engine = create_db_engine(self.url)
        init_db(self.engine)
        self.service = TraderService.__new__(TraderService)
        self.service.engine = self.engine
        self.service._snapshots_pruned = {}
        self.at = utcnow() - timedelta(days=4)
        self.end = self.at + timedelta(hours=2)
        self.row = UserAutomation(user_id="viewer", league_id="L", trader_flags={"decision_snapshots": "shadow"})
        self.debug = {"market": [], "sell_ratio": 1.0}
        self.listed = {}
        self.extra = {}
        for i in range(200):
            pid = str(i)
            value = (1, 6, 16)[i % 3] * 1000000
            self.debug["market"].append({"id": pid, "value": value, "reason": f"R{i % 4}",
                                         "expires_at": self.end.isoformat()})
            self.listed[pid] = SimpleNamespace(id=pid, listed_at=self.at, seller=None, expires_in=7200, offer_count=1)
            self.extra[pid] = {"hypothetical_bid": value + 10000, "cap": value + 20000, "ev": value + 20000}

    def snapshot(self):
        self.service._snapshot("L", self.row, self.debug, self.listed, self.extra, self.at, Options(snapshot_limit=3))

    def test_sampling_restart_settlement_and_archive(self):
        for _ in range(4):
            self.snapshot()
        with Session(self.engine) as db:
            rows = db.exec(select(DecisionSnapshot)).all()
            self.assertEqual(len(rows), 12)
            self.assertEqual(len({(r.reason, r.value) for r in rows}), 12)
            r = rows[0]
            pid, price = r.player_id, r.value
            start = analytics.market_value_day(self.end)
            db.add(Transfer(id="sale", league_id="L", player_id=pid, buyer_id="rival", price=price, date=self.end))
            db.add(MarketValueHistory(player_id=pid, points=[[start+i, price+i*20000] for i in range(4)]))
            db.add(TradeLog(user_id="viewer", league_id="L", player_id=pid, kind="sell", status="sold",
                            purpose="exit", profit=-7))
            db.add(TradeLog(user_id="other", league_id="L", player_id=pid, kind="sell", status="sold",
                            purpose="exit", profit=800))
            db.commit()
        self.engine.dispose()
        self.engine = create_db_engine(self.url)
        with Session(self.engine) as db:
            settle_due(db, "viewer", "L", utcnow())
            db.commit()
        report = shadow_report(self.engine, "viewer", "L")
        self.assertEqual(report["bids"]["standard"]["won"], 1)
        self.assertEqual(report["bids"]["minimum"]["unknown"], 12)
        self.assertEqual(report["learning"]["samples"], 1)
        self.assertEqual(report["sales"]["hold_2"]["median"], 30000)
        self.assertEqual(report["realized"]["sum"], -7)
        for scope in (("other", "L"), ("viewer", "other")):
            self.assertEqual(shadow_report(self.engine, *scope)["observed"], 0)
        with Session(self.engine) as db:
            self.assertEqual(archive_batch(db, "other", "L", utcnow()), 0)
            self.assertEqual(archive_batch(db, "viewer", "L", utcnow()), 12)
            db.rollback()
            self.assertEqual(len(db.exec(select(ShadowAnalysis)).all()), 12)
            self.assertEqual(archive_batch(db, "viewer", "L", utcnow()), 12)
            db.commit()
            self.assertEqual(archive_batch(db, "viewer", "L", utcnow()), 0)
            self.assertEqual(sum(r.count for r in db.exec(select(ShadowDaily))), 12)
            self.assertFalse(db.exec(select(ShadowAnalysis)).all())

    def test_real_purchase_and_unrelated_transfers(self):
        self.snapshot()
        with Session(self.engine) as db:
            rows = db.exec(select(ShadowAnalysis).order_by(ShadowAnalysis.player_id)).all()
            for i, row in enumerate(rows):
                db.add(Transfer(id=str(i), league_id="foreign" if i == 0 else "L", player_id=row.player_id,
                       date=self.end + timedelta(days=1 if i == 1 else 0), buyer_id="viewer", price=1000000))
            db.commit()
            settle_due(db, "viewer", "L", utcnow())
            db.commit()
        report = shadow_report(self.engine, "viewer", "L")
        self.assertEqual(report["categories"], {"unknown": 2, "purchased": 1})
        self.assertEqual(report["learning"]["samples"], 1)
        self.assertEqual(report["bids"]["aggressive"]["unknown"], 3)

    def test_final_empty_listing_and_ambiguous_evidence(self):
        self.snapshot()
        self.listed = {pid: obj for pid, obj in self.listed.items() if pid in ("0",)}
        for obj in self.listed.values():
            obj.expires_in, obj.offer_count = 0, 0
        from sync.shadow_analysis import record_closed_listings
        with Session(self.engine) as db:
            rows = db.exec(select(ShadowAnalysis).order_by(ShadowAnalysis.player_id)).all()
            pid = rows[-1].player_id
            for i in range(2):
                db.add(Transfer(id=str(i), league_id="L", player_id=pid, buyer_id="rival", price=10000, date=self.end))
            record_closed_listings(db, "viewer", "L", self.listed)
            settle_due(db, "viewer", "L", utcnow())
            db.commit()
            self.assertTrue(rows[0].result["no_buyer"])
            self.assertIsNone(rows[-1].result["winner_price"])
