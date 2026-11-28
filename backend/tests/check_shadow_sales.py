import unittest

from core.shadow_intelligence import sale_strategies


class SaleReplay(unittest.TestCase):
    def test_future_and_gaps(self):
        prices = {0: (100, 4), 1: (120, 3), 2: (110, -1), 3: (150, 4)}
        result = sale_strategies(0, prices, 1, 5, 2)
        self.assertEqual(result["exits"], {"hold_1": 120, "hold_2": 110, "hold_3": 150,
                         "deadline": 110, "trailing": 110, "forecast": 110})
        prices[3] = (2000, 7)
        future = sale_strategies(0, prices, 1, 5, 2)
        for name in ("forecast", "trailing", "deadline"):
            self.assertEqual(result["exits"][name], future["exits"][name])
        del prices[1]
        self.assertFalse(sale_strategies(0, prices, 1, 5, 2)["exits"])

    def test_categories(self):
        from core.shadow_intelligence import classify
        bids = {"bids": {"standard": 100}, "cap": 80}
        result = {"outcomes": {"standard": "won"}, "exits": {"hold_2": 90}}
        self.assertEqual(classify("BUDGET", bids, result), ("avoided", -10, "infeasible"))
        result["exits"] = {"hold_2": 110}
        self.assertEqual(classify("BUDGET", bids, result), ("missed", 10, "infeasible"))
        self.assertEqual(classify("BUDGET", {}, {})[:2], ("unknown", None))

    def test_weight(self):
        from core.shadow_intelligence import weighted_win_rate
        learn = weighted_win_rate([("a", False, False, 0), ("a", True, True, 0), ("b", False, False, 30)])
        self.assertEqual(learn["samples"], 2)
        self.assertEqual(learn["weight"], .25)
        self.assertAlmostEqual(learn["rate"], .8)
