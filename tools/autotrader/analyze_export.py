"""Offline analysis of an autotrader JSON export (GET /api/automation/trader/export).

    python -I tools/autotrader/analyze_export.py export.json [more.json ...] [--json]

Reads only the file, never Kickbase. Answers the first question of Auto-Trader 3.0 (E01.01):
why does a league get no buy proposals? Per export it prints the switches, the options that differ
from the defaults, the learned values that gate buying, the money picture of the latest rounds
(theoretical max bid vs. the budget the trader really released) and a histogram of the reasons the
market players were not bought, mapped to provisional reason codes (E01.02 makes them native).

Standard library only, so it runs anywhere with `python -I`.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

### Same rule as core.analytics.max_bid: balance plus 33 % of the team value
MAX_BID_SHARE = 0.33

### Defaults of core.trader.Options (kept in sync by hand; the export also carries "options")
DEFAULTS = {
    "min_gain": 2.0, "max_cost_per_point": 300_000, "min_avg_edge": 10, "min_play": 60, "lineup_share": 100,
    "profit_share": 60, "reserve": 0, "cover_max_price": 3_000_000, "daily_bids": 6, "daily_sales": 3,
    "stop_loss": 3_000_000, "sell_window": 20, "starter_lock": 60, "min_roi": 2.0, "credit_mode": 1,
    "trailing_stop": 5, "position_stop": 10, "max_hold_days": 7, "shadow": True, "rescue_override": False,
}

### Decision texts of sync/trader.py -> provisional reason code. First match wins, order matters
REASONS: list[tuple[str, str]] = [
    ("blockiert: ", "RISK_BLOCKED"),
    ("Gebot ", "BID_PLANNED"),
    ("eigenes Gebot offen", "OWN_BID_OPEN"),
    ("eigener Spieler", "OWN_PLAYER"),
    ("vor kurzem verkauft", "REBUY_BLOCK"),
    ("Vereinslimit", "CLUB_LIMIT"),
    ("keine Marktdaten", "NO_MARKET_DATA"),
    ("verletzt/fraglich", "NOT_FIT"),
    ("Gewinnhandel aus", "PROFIT_TRADING_OFF"),
    ("pausiert (Stop-Loss)", "STOP_LOSS"),
    ("pausiert (Prognose", "FORECAST_PAUSE"),
    ("letzte Stunde vor dem Spieltag", "PHASE_FINAL"),
    ("Auktionsende unbekannt", "AUCTION_END_UNKNOWN"),
    ("keine steigende Prognose", "NO_RISING_FORECAST"),
    ("Tageslimit Gebote", "DAILY_BIDS"),
    ("Platz schon durch ein Gebot", "SLOT_TAKEN_THIS_ROUND"),
    ("erst die Startelf füllen", "ELEVEN_GAPS_FIRST"),
    ("Position schon abgedeckt", "COVER_DONE"),
    ("kein Kaderplatz frei", "SQUAD_FULL"),
    ("Marge unter der Mindestmarge oder Budget zu knapp", "PROFIT_MARGIN_OR_BUDGET"),
    ("Budget oder Preis je Punkt passt nicht", "LINEUP_BUDGET_OR_PRICE_PER_POINT"),
    ("nicht geprüft", "NOT_CHECKED"),
]


def reason_code(text: str | None) -> str:
    if not text:
        return "NONE"
    for needle, code in REASONS:
        if needle in text:
            ### A "blockiert: X" suffix names the risk engine's own code
            return f"RISK_{text.rsplit('blockiert: ', 1)[1].strip()}" if code == "RISK_BLOCKED" else code
    return "OTHER"


def money(value: object) -> str:
    if not isinstance(value, (int, float)):
        return "–"
    return f"{value / 1e6:,.2f} Mio."


def round_summary(data: dict) -> dict:
    """The money picture of one stored round."""
    team_value = sum(int(p.get("value") or 0) for p in data.get("squad", []))
    budget = data.get("budget")
    open_bids = sum((data.get("open_bids") or {}).values())
    max_bid = max(0, round(budget + team_value * MAX_BID_SHARE)) if isinstance(budget, int) else None
    free = data.get("cash_free")
    credit = data.get("credit") or 0
    released_lineup = (free or 0) + (credit if data.get("credit_mode", 1) >= 1 else 0)
    released_profit = (free or 0) + (credit if data.get("credit_mode", 1) >= 2 and data.get("phase") == "normal" else 0)
    return {
        "phase": data.get("phase"), "budget": budget, "team_value": team_value, "open_bids": open_bids,
        "max_bid": max_bid, "max_bid_after_open_bids": None if max_bid is None else max_bid - open_bids,
        "cash_free": free, "credit": credit, "credit_mode": data.get("credit_mode"),
        "liquidation_logged": data.get("liquidation"), "profit_room": data.get("profit_room"),
        "released_lineup": released_lineup, "released_profit": released_profit,
        "gap": None if max_bid is None else max_bid - open_bids - max(released_lineup, released_profit),
        "slots": data.get("slots"), "bids_left": data.get("bids_left"), "sales_left": data.get("sales_left"),
        "paused": data.get("paused"), "forecast_paused": data.get("forecast_paused"),
        "gaps_confirmed": data.get("gaps_confirmed"), "gaps_projected": data.get("gaps_projected"),
        "league_auctions": data.get("league_auctions"), "actions": len(data.get("actions") or []),
        "risk_blocked": Counter(b.get("code") for b in data.get("risk_blocked") or []),
        "rescue": bool(data.get("rescue")),
    }


def analyze(export: dict) -> dict:
    rounds = [r.get("data") or {} for r in export.get("rounds", [])]
    normal = [d for d in rounds if not d.get("rescue")]
    reasons: Counter[str] = Counter()
    reasons_by_player: dict[str, set[str]] = {}
    for d in normal:
        for m in d.get("market", []):
            code = reason_code(m.get("decision"))
            reasons[code] += 1
            reasons_by_player.setdefault(code, set()).add(str(m.get("id")))
        for text in (d.get("skipped") or {}).values():
            reasons[reason_code(text)] += 1
    ### Profit trading at all possible? Best net result at the minimum bid of every rising, fit player
    rising = {m.get("id"): m for d in normal for m in d.get("market", []) if m.get("fit") and (m.get("forecast") or 0) > 0}
    nets = [m["net_at_low"] for m in rising.values() if isinstance(m.get("net_at_low"), (int, float))]
    gains = sorted(m["gain"] / m["value"] * 100 for m in rising.values() if m.get("value") and isinstance(m.get("gain"), (int, float)))
    profit_check = {
        "rising_players": len(rising), "net_positive_at_min_bid": sum(1 for n in nets if n > 0),
        "best_net_at_min_bid": max(nets) if nets else None,
        "median_gain_pct": round(gains[len(gains) // 2], 2) if gains else None,
        "max_gain_pct": round(gains[-1], 2) if gains else None,
        "sell_ratio": next((d.get("sell_ratio") for d in reversed(normal) if d.get("sell_ratio")), None),
    }
    options = export.get("options") or {}
    changed = {k: (DEFAULTS.get(k), v) for k, v in options.items() if k in DEFAULTS and DEFAULTS[k] != v}
    effective = export.get("learned_effective") or {}
    trades = export.get("trades") or []
    bids = Counter((t.get("purpose"), t.get("status")) for t in trades if t.get("kind") == "bid")
    shadows = Counter((s.get("purpose"), s.get("status")) for s in export.get("shadows") or [])
    return {
        "league_id": export.get("league_id"),
        "exported_at": export.get("exported_at"),
        "switches": export.get("switches"),
        "options_changed": changed,
        "learned": {k: effective.get(k) for k in ("min_margin", "gain_ratio", "gain_samples", "forecast_pause", "extra", "swap_edge")},
        "rounds": len(rounds), "rescue_rounds": len(rounds) - len(normal),
        "rounds_with_actions": sum(1 for d in normal if d.get("actions")),
        "latest": round_summary(normal[-1]) if normal else None,
        "profit_check": profit_check,
        "reasons": dict(reasons.most_common()),
        "players_per_reason": {k: len(v) for k, v in reasons_by_player.items()},
        "bids": {f"{p}/{s}": n for (p, s), n in bids.items()},
        "shadows": {f"{p}/{s}": n for (p, s), n in shadows.items()},
    }


def report(result: dict) -> str:
    lines = [f"Liga {result['league_id']} – Export {result['exported_at']}", f"Schalter: {result['switches']}"]
    lines.append("Geänderte Einstellungen: " + (", ".join(f"{k} {a}→{b}" for k, (a, b) in result["options_changed"].items()) or "keine"))
    lines.append(f"Gelernt (wirksam): {result['learned']}")
    lines.append(f"Runden: {result['rounds']} (Rettung {result['rescue_rounds']}), mit Aktionen: {result['rounds_with_actions']}")
    latest = result["latest"]
    if latest:
        lines.append("Letzte Runde:")
        for key in ("phase", "budget", "team_value", "open_bids", "max_bid", "max_bid_after_open_bids", "cash_free", "credit",
                    "credit_mode", "liquidation_logged", "profit_room", "released_lineup", "released_profit", "gap"):
            value = latest[key]
            lines.append(f"  {key:<26} {money(value) if isinstance(value, int) and key not in ('credit_mode',) else value}")
        for key in ("slots", "bids_left", "sales_left", "paused", "forecast_paused", "gaps_confirmed", "gaps_projected",
                    "league_auctions", "actions"):
            lines.append(f"  {key:<26} {latest[key]}")
        lines.append(f"  {'risk_blocked':<26} {dict(latest['risk_blocked'])}")
    pc = result["profit_check"]
    lines.append(
        f"Gewinnhandel möglich? {pc['net_positive_at_min_bid']} von {pc['rising_players']} steigenden Spielern netto positiv "
        f"beim Mindestgebot (bester: {money(pc['best_net_at_min_bid'])}); Prognose über den Haltezeitraum Median "
        f"{pc['median_gain_pct']} %, max. {pc['max_gain_pct']} %; Verkaufsquote {pc['sell_ratio']} "
        f"(Gewinnschwelle ≈ {round((1 / pc['sell_ratio'] - 1) * 100, 1) if pc['sell_ratio'] else '–'} % + Aufschlag)"
    )
    lines.append("Gründe ohne Kauf (alle Runden, Marktspieler-Runden):")
    for code, n in result["reasons"].items():
        lines.append(f"  {code:<36} {n:>6}  ({result['players_per_reason'].get(code, 0)} Spieler)")
    lines.append(f"Gebote: {result['bids'] or 'keine'}")
    lines.append(f"Schattentransfers: {result['shadows'] or 'keine'}")
    lines.append("Hinweis: 'liquidation_logged' rechnet mit dem vollen Tageslimit, der Kredit mit den restlichen Verkäufen (KNOWN_ISSUES KI-04).")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("exports", nargs="+", type=Path)
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args()
    ### German text and arrows also on a Windows console
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    results = [analyze(json.loads(path.read_text(encoding="utf-8"))) for path in args.exports]
    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False, default=dict))
    else:
        print("\n\n".join(report(r) for r in results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
