# E02 – Strategy Configuration Engine

Ziel des Epics: Strategieänderungen ohne Image-Build und Neustart, versioniert, validiert, je Liga, mit Rollback. Grundlage: ADR-002/003/004, `CONFIG_SCHEMA.md`.

Reihenfolge (ADR-008): E02.01 → E02.02 → **E02.08** → E02.03 → E02.04 → E02.05 → E02.06 → E02.07 → E02.09.

### E02.01 – Versioniertes Konfigurationsschema
- **Priorität:** P1 · **Status:** done · **Abhängig von:** E00 · **Aufwand:** M · **Flag:** –
- **Ergebnis:**
  - `core/strategy_config.py` definiert Schema v1 mit 32 Einstellungen: alle 22 Liga-Optionen (bearbeitbar) und 10 feste Regeln (nur lesbar, `fixed`). Jede Einstellung hat Pfad, Typ, Einheit, Grenzen, Standardwert und eine deutsche Erklärung.
  - Standardwerte und Grenzen der Optionen kommen direkt aus `Options`/`OPTION_LIMITS` und können nicht auseinanderlaufen.
  - `from_options`/`to_options` wandeln verlustfrei hin und zurück (alle Profile geprüft). `to_options` ist so tolerant wie `Options.load`.
  - `GET /api/automation/trader/schema` liefert das Schema als JSON für die Expertenoberfläche.
  - Tests: `check_strategy_config.py` (36 Checks, in CI) und eine Smoke-Prüfung (Schema und Einstellungsseite haben gleich viele Optionen).
  - Suite 18/18 grün. Handelsverhalten unverändert: Die Planung nutzt das Schema noch nicht, das kommt mit E02.04.
- **Abweichung von Abnahmekriterium 2 (begründet):** Die festen Konstanten sind als **nur lesbare** Felder im Schema, nicht bearbeitbar.
  - `PROFIT_HOLD` wirkt auf Prognosehorizont, Ranking, Schattenabrechnung, Lernen (`after_forecast` im selben Horizont) und Backtest. Ein konfigurierbarer Wert ändert dort das Verhalten und gehört hinter ein Flag.
  - Das übernimmt das neue Paket **E02.10**, je Regel einzeln. Die Standardwerte im Schema sind dieselben wie im Code (Test).
- **Ziel:** Eine Schema-Definition (Pfad, Typ, Einheit, Min, Max, Standard, Erklärung) als einzige Quelle; `StrategyConfig` (frozen dataclass) mit Abbildung auf das bestehende `Options`.
- **Umfang:** `core/strategy_config.py`: Schema v1 für die 20 bestehenden Optionen + erste feste Konstanten, die ohne Verhaltensänderung konfigurierbar werden können (`hold_updates`, `min_hold_hours`, `rebuy_block_days`, `prepare_hours`, `final_minutes`, `room_bid_extra`). `to_options()` liefert das bisherige `Options`. Standardwerte = heutige Konstanten.
- **Nicht enthalten:** Speicherung (E02.03), Import (E02.05).
- **Abnahmekriterien:** 1. `StrategyConfig.default().to_options() == Options()`. 2. Jede Konstante, die ins Schema wandert, wird im Code aus der Konfiguration gelesen, Standard identisch. 3. Schema als JSON exportierbar (für UI und Doku).
- **Pflichttests:** Rundlauf Options ↔ Config; alle Profile identisch abgebildet; Planung mit Default-Config = Planung 2.0 (Demo-Szenarien).
- **Migration:** keine · **Rollback:** Revert.

### E02.02 – Validierung und Sicherheitsgrenzen
- **Priorität:** P1 · **Status:** todo · **Abhängig von:** E02.01 · **Aufwand:** S
- **Ziel:** `validate(data) -> (config | None, errors[])` streng; `load(data)` tolerant (ADR-004).
- **Abnahmekriterien:** 1. Unbekannter Schlüssel, falscher Typ, NaN/∞, außerhalb Grenzen, Bool als Zahl → Fehler mit Pfad. 2. Kein Teil-Übernehmen bei Fehlern. 3. Alte Exporte (2.0-`options`) werden als Schema-v0 erkannt und migriert.
- **Pflichttests:** Fuzz-ähnliche Tabelle ungültiger Werte; Altformat.

### E02.08 – Feature-Flag-System (vorgezogen)
- **Priorität:** P1 · **Status:** todo · **Abhängig von:** E02.02 · **Aufwand:** S
- **Ziel:** `flags` im Schema; Helfer `stage(config, name) -> off|shadow|dry_run|live`, wobei `live` nur wirkt, wenn `row.trader_live` an ist (sonst höchstens `dry_run`).
- **Umfang:** Flag-Liste als Konstante (neue Flags nur per Code); Debug-Protokoll enthält die wirksamen Stufen.
- **Abnahmekriterien:** 1. Unbekanntes Flag im Import = Fehler. 2. Standard aller Flags `off`. 3. Test: `live`-Flag bei ausgeschaltetem Live-Handel wirkt als `dry_run`.
- **Sicherheit:** S14; Wechsel nach `live` erzeugt `AutomationEvent`.

### E02.03 – Ligaindividuelle Konfiguration speichern
- **Priorität:** P1 · **Status:** todo · **Abhängig von:** E02.08 · **Aufwand:** M
- **Ziel:** Tabelle `strategyconfig` (append-only, ADR-003); Migration der bestehenden `trader_options` als Version 1.
- **Abnahmekriterien:** 1. Migration erhält jeden bestehenden Wert (Test mit DB des Altstands, `check_trader_migration.py` erweitert). 2. `init_db` zweimal ohne Duplikate. 3. Isolation Nutzer/Liga. 4. `trader_options` wird weiter geschrieben (Downgrade-Fähigkeit).
- **Migration:** neue Tabelle per `create_all` (additiv, **ohne** `SCHEMA_VERSION`-Erhöhung, ADR-010) + idempotente Übernahme beim Start („für jede (Nutzer, Liga) ohne Version: Version 1 aus `trader_options`“). **Backup vor Update** (Release-Checkliste).
- **Rollback:** Image zurück; die alte Version startet (Schema-Version unverändert), ignoriert die neue Tabelle und liest `trader_options` (weiterhin aktuell geschrieben).

### E02.04 – Dynamische Übernahme ohne Neustart
- **Priorität:** P1 · **Status:** todo · **Abhängig von:** E02.03 · **Aufwand:** S
- **Ziel:** Jede Runde lädt die aktive Version einmal; `config_version` in Debug, TradeLog-`details`, Snapshots.
- **Abnahmekriterien:** 1. Änderung zwischen zwei Runden wirkt in der nächsten. 2. Änderung **während** einer Runde wirkt nicht in dieser (Test mit Haken zwischen Planung und Ausführung). 3. Kein zusätzlicher DB-Zugriff je Aktion (Cache je Runde).

### E02.05 – JSON-Import mit Änderungsvorschau
- **Priorität:** P2 · **Status:** todo · **Abhängig von:** E02.04 · **Aufwand:** M
- **Ziel:** `POST …/config/preview` (Diff alt→neu, Validierungsfehler, betroffene Flags) und `POST …/config/activate` (nur nach Vorschau, mit Notiz). Bestehender Import bleibt kompatibel und läuft über denselben Pfad.
- **Abnahmekriterien:** 1. Vorschau schreibt nichts. 2. Aktivierung atomar (eine Transaktion). 3. Gleichzeitige Aktivierung zweier Versionen: genau eine gewinnt, die andere erhält Konfliktfehler (optimistische Sperre über erwartete Vorgängerversion).

### E02.06 – Konfigurationshistorie und Vergleich
- **Priorität:** P2 · **Abhängig von:** E02.05 · **Aufwand:** S
- **Ziel:** Liste der Versionen mit Autor, Zeit, Notiz; Diff zweier beliebiger Versionen.

### E02.07 – Rollback
- **Priorität:** P2 · **Abhängig von:** E02.06 · **Aufwand:** S
- **Ziel:** Ältere Version erneut aktivieren = neue Version mit Inhalt der alten (Historie bleibt linear).
- **Abnahmekriterien:** Rollback einer Version mit inzwischen ungültigen Werten (Schema verschärft) wird abgelehnt mit Fehlerliste.

### E02.10 – Feste Regeln einzeln konfigurierbar machen (neu, aus E02.01)
- **Priorität:** P2 · **Status:** todo · **Abhängig von:** E02.04, E02.08 · **Aufwand:** je Regel S · **Flag:** je Regel
- **Ziel:** Die 10 `fixed`-Felder werden nacheinander bearbeitbar. Zuerst die ohne Lernwirkung (`matchday.min_hold_hours`, `matchday.rebuy_block_days`, `matchday.prepare_hours`, `matchday.final_minutes`, `auction.room_bid_extra`), danach die mit Lernwirkung (`profit.hold_updates` nur zusammen mit einem getrennten Lernzustand je Horizont).
- **Abnahmekriterien:** je Regel ein Determinismus-Test (Standardwert = altes Verhalten) und harte Grenzen; `final_minutes` < `prepare_hours` × 60.

### E02.09 – Expertenoberfläche (Strategy Studio, Teil 1)
- **Priorität:** P3 · **Abhängig von:** E02.06 · **Aufwand:** M
- **Ziel:** Standardmodus (Profile + wenige Regler) und Expertenmodus (alle Schemafelder, aus Schema generiert, mit Erklärung, Grenzen), Import/Export, Historie, Diff, Rollback, Flag-Schalter je Liga.
- **Abnahmekriterien:** 375 px ohne Überlauf; riskante Änderungen (Flags → `live`, `credit_mode 2`, Auslastung > 80 %) mit Bestätigung.
