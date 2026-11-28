# Konfigurationsschema

Status: **Entwurf** (wird mit E02.01 verbindlich). Teil A beschreibt den Ist-Zustand, Teil B das geplante Schema v1.

## A. Ist-Zustand (2.0)

**Je Liga einstellbar** (`core/trader.py::Options`, Grenzen `OPTION_LIMITS`, gespeichert in `userautomation.trader_options`):

| Schlüssel | Standard | Grenzen | Bereich (Schema v1) |
|---|---|---|---|
| `min_gain` | 2,0 | 0–100 | `sport.min_points_gain` |
| `max_cost_per_point` | 300.000 | 0–50 Mio. | `sport.max_cost_per_point` |
| `min_avg_edge` | 10 | 0–200 % | `sport.min_quality_edge_pct` |
| `min_play` | 60 | 0–100 % | `sport.min_play_pct` |
| `lineup_share` | 100 | 10–100 % | `finance.lineup_cash_share_pct` |
| `profit_share` | 60 | 10–100 % | `profit.max_total_share_pct` |
| `reserve` | 0 | 0–500 Mio. | `finance.reserve` |
| `cover_max_price` | 3 Mio. | 0–50 Mio. | `bench.max_price` |
| `daily_bids` / `daily_sales` | 6 / 3 | 0–30 | `limits.daily_bids` / `limits.daily_sales` |
| `stop_loss` | 3 Mio. | 0–100 Mio. | `profit.weekly_stop_loss` |
| `sell_window` | 20 | 5–180 min | `auction.room_sale_window_min` |
| `starter_lock` | 60 | 0–1440 min | `matchday.starter_lock_min` |
| `min_roi` | 2,0 | 0–100 % | `profit.min_roi_pct` |
| `credit_mode` | 1 | 0–2 | `finance.credit_mode` (bleibt; E04.07 ergänzt `max_utilization_pct`) |
| `trailing_stop` / `position_stop` / `max_hold_days` | 5 / 10 / 7 | 0–50 / 0–100 / 0–60 | `profit.trailing_stop_pct` … |
| `snapshot_limit` | 32 | 1–200 je Runde | `learning.snapshot_limit` |
| `snapshot_days` | 120 | 7–365 Tage | `learning.snapshot_days` |
| `shadow` / `rescue_override` | an / aus | bool | `learning.shadow_enabled` / `matchday.rescue_override` |

**Fest im Code** (Kandidaten für Schema v1, jeweils mit harten Grenzen): siehe `KNOWN_ISSUES.md` KI-07. Bewusst **nicht** konfigurierbar bleiben: Gebotsschritt 10.000 €, 33-%-Regel, Abgleich-/Pausenlogik für unklare Aufrufe, Leader-Lease, Kill-Switches.

## B. Schema v1 (geplant, E02.01)

```jsonc
{
  "schema_version": 1,
  "profile": "balanced",            // Ausgangsprofil; Werte darunter überschreiben es
  "finance": {
    "reserve": 0,                    // € nie ausgegeben
    "credit_mode": 1,                // 0 nie, 1 Startelf/Ersatz, 2 auch Gewinnhandel (wie 2.0)
    "max_utilization_pct": 100,      // E04.07: Anteil des freigegebenen Kredits, 0–100
    "lineup_cash_share_pct": 100,
    "deadline_reserve": 0,           // € Puffer über 0 zum Anpfiff (pessimistisch)
    "stress_value_drop_pct": 3,      // E04.03: Marktwertabschlag je Update im Stressszenario
    "multi_day_liquidation": false,  // nur wirksam mit Flag multi_day_liquidation
    "api_outage_buffer_hours": 6     // Verkäufe, die in dieser Zeit vor der Deadline nötig wären, zählen nicht
  },
  "profit": { "min_margin_floor": 50000, "min_roi_pct": 2.0, "hold_updates": 2, "max_total_share_pct": 60,
              "max_position_share_pct": 100, "weekly_stop_loss": 3000000, "trailing_stop_pct": 5,
              "position_stop_pct": 10, "max_hold_days": 7 },
  "sport": { "min_points_gain": 2.0, "min_quality_edge_pct": 10, "min_play_pct": 60, "max_cost_per_point": 300000,
             "weights": { "average": 0.6, "form": 0.4 }, "lookahead_matches": 3 },
  "bench": { "strategy": "full_cover", "max_price": 3000000, "max_total_budget": null },
  "auction": { "room_sale_window_min": 20, "room_bid_extra": 0.6, "bid_grid": 40, "min_auctions": 8 },
  "learning": { "mode": "assisted", "shadow_enabled": true, "shadow_weight": 0.5, "min_samples": 10,
                "auto_parameters": [] },
  "matchday": { "prepare_hours": 24, "final_minutes": 60, "starter_lock_min": 60, "rescue_override": false,
                "min_hold_hours": 20, "rebuy_block_days": 7 },
  "limits": { "daily_bids": 6, "daily_sales": 3 },
  "flags": { "reason_codes": "live", "multi_day_liquidation": "off", "conditional_repayment": "off",
             "upgrade_financing": "off", "decision_snapshots": "off", "flexible_bench": "off" },
  "rules": []                        // E08.01: deklarative Regeln, siehe unten
}
```

### Validierungsregeln (E02.02)

- Jeder Schlüssel hat Typ, Einheit, Minimum, Maximum, Standard und eine deutsche Erklärung (eine Quelle: Schema-Definition in `core/strategy_config.py`, daraus werden Doku, UI-Regler und Validierung erzeugt).
- **Streng beim Import:** unbekannter Schlüssel, falscher Typ, NaN/Infinity, Wert außerhalb der Grenzen → Fehler mit Pfad (`finance.reserve: über 500 Mio.`), nichts wird übernommen.
- **Tolerant beim Laden gespeicherter Daten:** wie `Options.load` (Klemmen, Standard bei Müll) plus Warnung im Debug-Protokoll.
- Querregeln, z. B. `final_minutes < prepare_hours × 60`, `trailing_stop_pct < position_stop_pct` nicht nötig, aber `hold_updates ≥ 1`.
- `flags.*` ∈ {`off`, `shadow`, `dry_run`, `live`}; `live` nur, wenn der Liga-Schalter „Live handeln“ an ist; sonst wirkt höchstens `dry_run`.

### Migration

- Bestehende `trader_options` → Version 1 je (Nutzer, Liga), `created_by = "migration"`. Die alte Spalte bleibt und wird weiter geschrieben, solange 2.0 als Rückfall unterstützt wird (Downgrade ohne Datenverlust).
- Ältere `schema_version` → Migrationsfunktionen `migrate_v<n>_to_v<n+1>` mit Test je Schritt.

### Regelwerk (E08.01, Entwurf)

```jsonc
{ "id": "far-from-deadline", "when": [{ "metric": "hours_to_deadline", "op": ">=", "value": 120 }],
  "then": [{ "set": "profit.max_total_share_pct", "value": 70 }] }
```
Erlaubte `metric`s und `set`-Ziele sind feste Listen im Code. Keine Ausdrücke, keine Funktionen, kein Code. `then` darf nur innerhalb der Schemagrenzen setzen; harte Sicherheitsregeln sind keine `set`-Ziele.
