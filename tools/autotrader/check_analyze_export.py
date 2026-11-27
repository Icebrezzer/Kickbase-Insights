"""Checks of analyze_export.py on a small hand-made export. python -I tools/autotrader/check_analyze_export.py"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import analyze_export as ax  # noqa: E402

EXPORT = {
    "league_id": "4242", "exported_at": "2026-11-27T10:00:00+00:00",
    "switches": {"trader": True, "live": False, "profit": True},
    "options": {**ax.DEFAULTS, "credit_mode": 1, "min_roi": 3.0},
    "learned_effective": {"min_margin": 400_000, "gain_ratio": 0.8, "forecast_pause": 0},
    "trades": [], "shadows": [{"purpose": "near", "status": "watching"}],
    "rounds": [
        {"data": {"rescue": True, "phase": "repay", "budget": -1_000_000}},
        {"data": {
            "phase": "normal", "budget": 0, "cash_free": 0, "credit": 20_000_000, "credit_mode": 1,
            "liquidation": 25_000_000, "profit_room": 60_000_000, "open_bids": {"9": 1_000_000},
            "squad": [{"value": 50_000_000}, {"value": 50_000_000}],
            "actions": [], "risk_blocked": [{"code": "OVER_BUDGET"}],
            "market": [
                {"id": "1", "decision": "Gewinnhandel: Marge unter der Mindestmarge oder Budget zu knapp",
                 "fit": True, "forecast": 50_000, "gain": 200_000, "value": 10_000_000, "net_at_low": -120_000},
                {"id": "6", "decision": "Gewinnhandel: Gebot 1,000,000 € (x)",
                 "fit": True, "forecast": 90_000, "gain": 1_500_000, "value": 10_000_000, "net_at_low": 250_000},
                {"id": "2", "decision": "kein Startelf-Upgrade, keine steigende Prognose"},
                {"id": "3", "decision": "Startelf: Gebot 1,000,000 € (x) – blockiert: OVER_BUDGET"},
                {"id": "4", "decision": "etwas Neues"},
            ],
            "skipped": {"5": "Vereinslimit"},
        }},
    ],
}


def main() -> None:
    result = ax.analyze(EXPORT)
    latest = result["latest"]
    assert result["rounds"] == 2 and result["rescue_rounds"] == 1, result
    assert latest["team_value"] == 100_000_000 and latest["max_bid"] == 33_000_000, latest
    assert latest["max_bid_after_open_bids"] == 32_000_000, latest
    ### credit_mode 1: credit only for lineup and cover, profit trades see the cash alone
    assert latest["released_lineup"] == 20_000_000 and latest["released_profit"] == 0, latest
    assert latest["gap"] == 12_000_000, latest
    reasons = result["reasons"]
    assert reasons["PROFIT_MARGIN_OR_BUDGET"] == 1 and reasons["NO_RISING_FORECAST"] == 1, reasons
    assert reasons["RISK_OVER_BUDGET"] == 1 and reasons["OTHER"] == 1 and reasons["CLUB_LIMIT"] == 1, reasons
    pc = result["profit_check"]
    assert pc["rising_players"] == 2 and pc["net_positive_at_min_bid"] == 1 and pc["best_net_at_min_bid"] == 250_000, pc
    assert result["options_changed"] == {"min_roi": (2.0, 3.0)}, result["options_changed"]
    assert ax.reason_code(None) == "NONE"
    assert "Liga 4242" in ax.report(result)
    print("All export analysis checks passed.")


if __name__ == "__main__":
    main()
