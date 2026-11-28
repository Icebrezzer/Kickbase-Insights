"""Standalone tests: python -m unittest discover -s tests -p check_shadow_intelligence.py."""
import unittest
from collections import Counter

from core.shadow_intelligence import (
    AuctionEvidence, AuctionOutcome, Candidate, bid_variants, select_candidates, settle_bids,
)


class ShadowTests(unittest.TestCase):
    def test_sampling_budget_and_coverage(self):
        rows = [Candidate(str(i), 'a', i % 5, f'R{i % 4}') for i in range(200)]
        existing = set()
        counts = Counter()
        for _ in range(4):
            selected = select_candidates(rows, existing, counts, 5)
            self.assertEqual(len(selected), 5)
            self.assertTrue(all(c.key not in existing for c in selected))
            existing.update(c.key for c in selected)
            counts.update(c.stratum for c in selected)
        self.assertEqual(len(counts), 20)
        self.assertEqual(len(existing), 20)

    def test_duplicates_and_order(self):
        rows = [Candidate('p', 'a', 1, 'B'), Candidate('p', 'a', 1, 'A')]
        self.assertEqual(select_candidates(rows, set(), {}, 10),
                         select_candidates(reversed(rows), set(), {}, 10))
        self.assertEqual(len(select_candidates(rows, set(), {}, 10)), 1)
        self.assertEqual(select_candidates(rows, {('p', 'a')}, {}, 10), [])
        self.assertEqual(select_candidates(rows, set(), {}, 0), [])
        with self.assertRaises(ValueError):
            select_candidates(rows, set(), {}, -1)

    def test_bid_bounds(self):
        bids = bid_variants(1_001_000, 1_030_000, 1_035_000)
        self.assertEqual(bids['minimum'], 1_010_000)
        self.assertTrue(all(1_010_000 <= x <= 1_030_000 and x % 10_000 == 0 for x in bids.values()))
        self.assertEqual(bid_variants(1_001_000, None, 1_005_000), {})
        with self.assertRaises(ValueError):
            bid_variants(100, None, None, step=0)

    def test_outcomes(self):
        bids = {'low': 100, 'equal': 110, 'high': 120}
        self.assertEqual([v.outcome for v in settle_bids(bids, AuctionEvidence(110))],
                         [AuctionOutcome.LOST, AuctionOutcome.UNKNOWN, AuctionOutcome.WON])
        self.assertTrue(all(v.outcome == AuctionOutcome.UNKNOWN for v in settle_bids(bids, AuctionEvidence())))
        self.assertTrue(all(v.outcome == AuctionOutcome.NO_BUYER for v in settle_bids(bids, AuctionEvidence(confirmed_no_buyer=True))))
        with self.assertRaises(ValueError):
            AuctionEvidence(110, True)


if __name__ == '__main__':
    unittest.main()
