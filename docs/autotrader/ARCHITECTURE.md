# Architektur Auto-Trader – Ist und Ziel

Fachliche Details von 2.0: `AUTOTRADER.md`. Dieses Dokument beschreibt Module, Datenflüsse und die geplanten Erweiterungen von 3.0.

## 1. Ist-Zustand (Code-Stand `4b85715`)

### 1.1 Module

| Schicht | Datei | Zeilen | Rolle |
|---|---|---:|---|
| Reine Logik | `backend/core/trader.py` | 795 | `Options` (20 Einstellungen, `OPTION_LIMITS`, Profile), `Candidate`, Upgrade-/Ersatz-/Verkaufslogik, `liquidation_value`, `credit`, Phasen, Netto-Gewinn, Prioritäten, `exit_reason`, Gewinnchance (`best_bid`), `Learned` + Lernregeln |
| Reine Logik | `backend/core/risk.py` | 188 | Risk Engine: `validate(actions, Context)` → Reason Code je Aktion; `credit_for` |
| Reine Logik | `backend/core/coach.py` | 964 | Beste Elf, Prognose (`forecast`), Rettungsverkäufe, Preisklassen, `BID_STEP` |
| Reine Logik | `backend/core/analytics.py` | 684 | `max_bid` (Kontostand + 33 % Teamwert), Marktwert-Update-Zeiten, Deltas |
| Reine Logik | `backend/core/learning.py` | 277 | Erwartungsgewichte, Verkaufsquote (Median), Gebotslücken |
| Reine Logik | `backend/core/backtest.py` | 261 | Walk-Forward-Backtest des Gewinnhandels auf echten Auktionen |
| Ablauf | `backend/sync/trader.py` | 1529 | `TraderService`: Runde, `_settle`, `_settle_shadows`, `_plan` (≈450 Zeilen), `_execute`, Export/Import, Dashboard, Statistik |
| Ablauf | `backend/sync/automation.py` | 1226 | Scheduler-Tick, Sperren je Nutzer/Liga, Leader-Lease, Aufstellung, Scout, ruft `TraderService.round` |
| Ablauf | `backend/sync/learning.py` | 473 | `LearningService`: periodisches Fitten (Erwartung, Bieter, Verkaufsquote, Auktionen) |
| API | `backend/api/routes.py`, `insights.py`, `schemas.py` | – | `/api/automation/trader/*` (view, dashboard, export, import, profiles, backtest, reset) |
| Client | `backend/kickbase/client.py`, `models.py`, `demo.py` | – | Kickbase-HTTP (kein Retry bei Writes), Pydantic-Modelle, `DemoWorld` |
| Daten | `backend/db/models.py`, `db/__init__.py` | – | SQLModel; Schema-Version 2, additive Spalten über `_LATER_COLUMNS`, Migrationen `_MIGRATIONS` |
| UI | `frontend/src/pages/Automation.tsx` | 1115 | Automatik-Seite: Schalter, Feineinstellungen, Profile mit Vorschau, Dashboard, Backtest, Export/Import |

### 1.2 Ablauf einer Runde

```
automation.tick (Leader, alle 5 min) ── Sperre (user, league)
  └─ TraderService.round
       ├─ Schalter → Daten (Kader, Budget, Markt, Aufstellung)  [Kickbase-Lesezugriffe]
       ├─ _settle            unklare/offene Gebote abgleichen, after_auction lernen
       ├─ _settle_shadows    Papier-Käufe/-Verkäufe abrechnen, lernen (halbes Gewicht)
       ├─ _plan              Kandidaten → Prioritäten → Gebote/Verkäufe   (rein, DB-Lesen)
       │    └─ finish → risk.validate → Debug-Protokoll (TraderDebug)
       ├─ _execute (Live)    je Aktion: _revalidate → pending → Kickbase → Status
       └─ Push
```

### 1.3 Daten

| Tabelle | Inhalt | Aufbewahrung |
|---|---|---|
| `userautomation` | Schalter + `trader_options` (JSON) je Nutzer/Liga | dauerhaft |
| `tradelog` | echte und Probelauf-Aktionen mit Status, Preis, Gewinn | 60 Tage für Planung gelesen, dauerhaft gespeichert |
| `traderdebug` | Rundendaten (JSON), nur bei Änderung | 21 Tage |
| `shadowtrade` | Papier-Käufe/-Verkäufe je Nutzer/Liga | 120 Tage nach Abschluss |
| `modelstate` | `trader` (global), `trader:<liga>`, `sell_ratio`, `expectation:<comp>`, … | dauerhaft |
| `auctionlog`, `transfer`, `bidhistory` | Auktions- und Transferdaten der Liga | dauerhaft |
| `automationevent` | Ereignisse (u. a. `trader-import` mit Vorher-Werten) | dauerhaft |

### 1.4 Wo Geld entsteht (Ist)

```
free        = budget − reserve − Σ offene Gebote
max_bid     = budget + 0,33 × team_value          (nur in analytics, NICHT in der Planung)
liquidation = Σ (value + min(forecast,0)) × ratio über entbehrliche Spieler, ≤ sales_left (heute)
loan        = max(0, min(max_bid − max(budget,0), liquidation − max(0,−budget)))
money(c)    = free + credit_for(purpose, phase, mode)   − keep (Lücken- und Ersatzreserve)
```

## 2. Zielarchitektur 3.0

Grundsatz: **erweitern statt ersetzen.** Neue Bausteine sind reine Funktionen in `core/`, die `sync/trader.py` aufruft. Jeder Baustein hängt an einem Feature Flag; bei `off` läuft exakt der bisherige Pfad.

```
                 ┌──────────────────────── Strategy Configuration Engine (E02) ─────────────────────┐
                 │ core/strategy_config.py  Schema v1, Validierung, Profile, Flags, Versionen       │
                 │ db: strategyconfig (versioniert, je Liga), aktive Version je Runde im Debug-Log  │
                 └───────────────┬──────────────────────────────────────────────────────────────────┘
                                 │ StrategyConfig (unveränderlich je Runde)
  Daten (wie heute) ──► _plan ───┼──► core/finance.py      (E04) Liquiditätsplan, Szenarien, Sicherheiten-Register,
                                 │                              bedingte Tilgung, Kreditfreigabe, Tilgungsplan
                                 ├──► core/squad_roles.py  (E05) Rollen, Ersatzbank-Strategie
                                 ├──► core/trading.py      (E06) Opportunitätskosten, Rotation, Haltedauer
                                 ├──► core/trader.py/best_bid (E07 erweitert)
                                 └──► core/reasons.py      (E01) Reason Codes, Diagnose-Aggregat
                                        │
                          risk.validate (unabhängig, erweitert um Finanzplan-Prüfung)
                                        │
           ┌────────────────────────────┴─────────────────────────────┐
           ▼                                                          ▼
   Ausführung (unverändert)                           Shadow Intelligence (E03)
                                                       core/shadow.py + db: decisionsnapshot
                                                       nur bereits geladene Daten, keine Kickbase-Aufrufe
                                                              │
                                              Shadow Portfolios (E09) core/portfolio.py
                                                              │
                                              Adaptive Learning (E10) core/adaptive.py
                                              Vorschläge → Freigabe → neue Konfig-Version
```

### 2.1 Neue Bausteine (geplant)

| Baustein | Datei (neu) | Epic | Abhängig von |
|---|---|---|---|
| Reason Codes + Diagnose | `core/reasons.py` | E01 | – |
| Strategie-Konfiguration | `core/strategy_config.py`, Tabelle `strategyconfig` | E02 | E01.02 (Codes für Ablehnungen bei Validierung) |
| Feature Flags | Teil von `strategy_config` (`flags`) | E02.08 | E02.01 |
| Entscheidungs-Snapshots | `core/shadow.py`, Tabelle `decisionsnapshot` | E03 | E01.02, E02.01 (Versionsnummer) |
| Finanzplanung | `core/finance.py` | E04 | E02.08, E01.04 |
| Rollen/Ersatzbank | `core/squad_roles.py` | E05 | E02, E04.05 |
| Kapital/Haltedauer | `core/trading.py` | E06 | E04, E03.05 |
| Regelwerk | `core/rules.py` | E08 | E02 |
| Portfolios | `core/portfolio.py`, Tabellen `shadowportfolio*` | E09 | E03, E04 |
| Adaptives Lernen | `core/adaptive.py` | E10 | E02.06, E03, E09 |

### 2.2 Architekturentscheidungen

Siehe `DECISIONS.md` (ADR-001 ff.). Wichtigste:
- Konfiguration in der Datenbank, versioniert, je Runde einmal geladen (Hot Reload ohne Neustart, keine Änderung mitten in einer Runde).
- Finanzplanung als reine Funktion mit explizitem Sicherheiten-Register; die Risk Engine prüft den Plan unabhängig nach.
- Schatten- und Portfolio-Simulation ausschließlich auf Daten, die die Runde ohnehin lädt.
- `sync/trader.py::_plan` wird schrittweise entlastet: neue Logik kommt nicht in `_plan`, sondern in `core/*` mit Tests.

### 2.3 Performance-Budget

Heute: Planung ~0,1 s in der Demo, 48 SQL-Abfragen je Planung (Audit). Ziel: Jede Erweiterung bleibt unter **+20 % Laufzeit und +5 Abfragen je Runde**; Simulationen (Portfolios, Was-wäre-wenn) laufen gedrosselt und nicht in jeder Runde (`simulation_intensity`). Messung mit `backend/tests/benchmark_audit.py`.
