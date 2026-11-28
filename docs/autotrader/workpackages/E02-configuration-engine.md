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
- **Priorität:** P1 · **Status:** done · **Abhängig von:** E02.01 · **Aufwand:** S
- **Ergebnis:**
  - `strategy_config.validate(data, base)` prüft streng und liefert entweder die vollständige Konfiguration oder `None` mit allen Fehlern samt Pfad und deutschem Grund.
  - Abgelehnt werden: unbekannter Bereich, unbekannte Einstellung, falscher Typ (Text statt Zahl, `true` als Zahl, `"false"` als Bool), NaN/∞, Kommazahl statt ganzer Zahl, Werte außerhalb der Grenzen, unzulässige Auswahl, geänderte feste Regel sowie eine neuere oder ungültige `schema_version`.
  - Fehlende Einstellungen behalten den Wert der Basis.
  - Die flachen Optionen eines 2.0-Exports werden über `upgrade` erkannt und genauso streng geprüft.
  - Der tolerante Ladeweg (`to_options` / `Options.load`) bleibt für gespeicherte Daten unverändert.
  - Tests: 22 neue Checks in `check_strategy_config.py`.
  - Der Import-Endpunkt nutzt die Validierung noch nicht; das geschieht mit E02.05 (Vorschau und Aktivierung).
- **Ziel:** `validate(data) -> (config | None, errors[])` streng; `load(data)` tolerant (ADR-004).
- **Abnahmekriterien:** 1. Unbekannter Schlüssel, falscher Typ, NaN/∞, außerhalb Grenzen, Bool als Zahl → Fehler mit Pfad. 2. Kein Teil-Übernehmen bei Fehlern. 3. Alte Exporte (2.0-`options`) werden als Schema-v0 erkannt und migriert.
- **Pflichttests:** Fuzz-ähnliche Tabelle ungültiger Werte; Altformat.

### E02.08 – Feature-Flag-System (vorgezogen)
- **Priorität:** P1 · **Status:** done · **Abhängig von:** E02.02 · **Aufwand:** S
- **Ergebnis:**
  - `core/flags.py` kennt die Stufen `off`/`shadow`/`dry_run`/`live` und eine feste Liste von 5 Flags für die geplanten Funktionen E03.01, E05.02, E04.02, E04.04 und E04.05. Jedes Flag hat eine Erklärung und steht standardmäßig auf `off`.
  - `load` (tolerant), `validate` (streng) und `effective`: `live` wirkt nur bei eingeschaltetem „Live handeln“, sonst höchstens als `dry_run`.
  - Gespeichert wird in der neuen Spalte `userautomation.trader_flags` (additiv, ADR-010). Die Einstellungsseite schreibt sie nie, ein älteres Image ignoriert sie (geprüft).
  - API: `GET` und `PUT /api/automation/trader/flags`. Ein unbekanntes Flag oder eine unbekannte Stufe ergibt 422, ohne Änderung. `live` braucht `confirm_live`, sonst 400. Die Änderung läuft unter derselben Sperre wie die Trader-Runde, also nie mitten in einer Runde.
  - Jede Änderung wird als Ereignis `trader-flags` mit Vorher/Nachher protokolliert.
  - Jede Runde schreibt die wirksamen Stufen ins Debug-Protokoll (`flags`), der Export enthält die gespeicherten.
  - Tests: `check_feature_flags.py` (13 Checks, in CI) und 12 Smoke-Prüfungen.
  - Noch wirkt kein Flag: Die Funktionen kommen mit ihren Paketen, die jeweils den Determinismus-Test bei `off` mitbringen.
- **Abweichung (begründet):** `sell_ratio` und `upgrade_cross_position` bleiben Liga-Optionen und werden nicht zu Flags.
  - Die Verkaufsquote ist ein Fakt über Kickbase, kein Funktionsschalter.
  - Der Formationsschalter ist ein reiner Ein/Aus-Wert ohne Schatten- oder Probelauf-Stufe und vom Auftraggeber bereits fachlich entschieden. Ihn zu verschieben, würde gespeicherte Einstellungen umziehen, ohne Nutzen.
- **Ziel:** `flags` im Schema; Helfer `stage(config, name) -> off|shadow|dry_run|live`, wobei `live` nur wirkt, wenn `row.trader_live` an ist (sonst höchstens `dry_run`).
- **Umfang:** Flag-Liste als Konstante (neue Flags nur per Code); Debug-Protokoll enthält die wirksamen Stufen.
- **Abnahmekriterien:** 1. Unbekanntes Flag im Import = Fehler. 2. Standard aller Flags `off`. 3. Test: `live`-Flag bei ausgeschaltetem Live-Handel wirkt als `dry_run`.
- **Sicherheit:** S14; Wechsel nach `live` erzeugt `AutomationEvent`.

### E02.03 – Ligaindividuelle Konfiguration speichern
- **Priorität:** P1 · **Status:** done · **Abhängig von:** E02.08 · **Aufwand:** M
- **Ergebnis:**
  - Tabelle `strategyconfig` (Nutzer, Liga, Version; nur anhängend, genau eine aktiv). `sync/strategy.py::StrategyStore` legt beim ersten Zugriff Version 1 aus `trader_options` an (`created_by = migration`), ohne Startmigration und idempotent; wenn zwei Prozesse gleichzeitig anlegen, gewinnt einer.
  - `activate` schreibt die neue Version in einer Transaktion unter der prozessübergreifenden Sperre `strategy-config`. Optional wird eine erwartete Version geprüft, sonst `ConfigConflict`. Dabei werden auch `trader_options` zurückgeschrieben, damit 2.0-Leser und ältere Images dieselben Werte sehen.
  - `follow_options` erzeugt eine Version nur bei echter Änderung. Das betrifft die Einstellungsseite (`settings`) und den bisherigen Options-Import (`import`).
  - Abnahme:
    1. Jeder bestehende Wert bleibt erhalten (Test mit 2.0-Optionen inklusive `sell_ratio`).
    2. `init_db` mehrfach ohne Duplikate.
    3. Isolation nach Nutzer und Liga.
    4. `trader_options` wird weiter geschrieben.
  - Ein älteres Image (`4b85715`) startet auf der neuen Datenbank und schreibt weiter (geprüft).
  - Tests: `check_strategy_store.py` (18 Checks, in CI; auch zwei gleichzeitige Aktivierungen, nur eine gewinnt).
- **Ziel:** Tabelle `strategyconfig` (append-only, ADR-003); Migration der bestehenden `trader_options` als Version 1.
- **Abnahmekriterien:** 1. Migration erhält jeden bestehenden Wert (Test mit DB des Altstands, `check_trader_migration.py` erweitert). 2. `init_db` zweimal ohne Duplikate. 3. Isolation Nutzer/Liga. 4. `trader_options` wird weiter geschrieben (Downgrade-Fähigkeit).
- **Migration:** neue Tabelle per `create_all` (additiv, **ohne** `SCHEMA_VERSION`-Erhöhung, ADR-010) + idempotente Übernahme beim Start („für jede (Nutzer, Liga) ohne Version: Version 1 aus `trader_options`“). **Backup vor Update** (Release-Checkliste).
- **Rollback:** Image zurück; die alte Version startet (Schema-Version unverändert), ignoriert die neue Tabelle und liest `trader_options` (weiterhin aktuell geschrieben).

### E02.04 – Dynamische Übernahme ohne Neustart
- **Priorität:** P1 · **Status:** done · **Abhängig von:** E02.03 · **Aufwand:** S
- **Ergebnis:**
  - `TraderService.round` lädt die aktive Konfiguration einmal und gibt sie an `_plan` und an die Neuplanung vor jeder Live-Aktion (`_revalidate`) weiter. Eine Änderung während der Runde wirkt erst in der nächsten.
  - Ohne übergebene Konfiguration (Tests, Einzelaufruf) lädt `_plan` die aktive.
  - Die Version steht im Debug-Protokoll (`config_version`), in jeder geplanten Aktion und in den Details jedes Handelsprotokoll-Eintrags. Der Export enthält die aktive Konfiguration.
  - Kein zusätzlicher DB-Zugriff je Aktion.
  - Die geplanten Aktionen des Smoke-Tests sind vor und nach der Änderung identisch.
  - Tests (Smoke): Speichern ohne Änderung erzeugt keine Version, mit Änderung schon; die Runde protokolliert ihre Version; eine festgehaltene Konfiguration hat Vorrang vor der gespeicherten; jede Aktion trägt die Version.
- **Ziel:** Jede Runde lädt die aktive Version einmal; `config_version` in Debug, TradeLog-`details`, Snapshots.
- **Abnahmekriterien:** 1. Änderung zwischen zwei Runden wirkt in der nächsten. 2. Änderung **während** einer Runde wirkt nicht in dieser (Test mit Haken zwischen Planung und Ausführung). 3. Kein zusätzlicher DB-Zugriff je Aktion (Cache je Runde).

### E02.05 – JSON-Import mit Änderungsvorschau
- **Priorität:** P2 · **Status:** done · **Abhängig von:** E02.04 · **Aufwand:** M
- **Ergebnis:**
  - Neue Endpunkte:
    - `GET /api/automation/trader/config`: aktive Version mit Daten und Historie.
    - `POST …/config/preview`: streng gegen die aktive Version geprüft, liefert alle Fehler mit Pfad und alle Änderungen alt → neu mit Erklärung; schreibt nichts.
    - `POST …/config/activate`: nur gültig (sonst 422, keine Änderung), nur mit der `expected_version` aus der Vorschau (sonst 422, bei zwischenzeitlicher Änderung 409). Läuft unter der Rundensperre, wirkt ab der nächsten Runde und wird als Ereignis `trader-config` mit allen Änderungen protokolliert.
  - Akzeptiert vollständige oder teilweise Konfigurationen und die flachen Optionen eines 2.0-Exports.
  - Der bisherige `POST …/trader/import` bleibt unverändert kompatibel (tolerant, klemmt Werte) und erzeugt über E02.03 eine Version.
  - Tests: Smoke (Vorschau schreibt nichts, ungültig ändert nichts, Konflikt 409, Einstellungsseite zeigt die Werte, Ereignis, 2.0-Optionen) und `diff`-Checks in `check_strategy_config.py`.
  - Die Historienliste von E02.06 ist damit teilweise vorhanden; der Vergleich zweier beliebiger Versionen fehlt noch.
- **Ziel:** `POST …/config/preview` (Diff alt→neu, Validierungsfehler, betroffene Flags) und `POST …/config/activate` (nur nach Vorschau, mit Notiz). Bestehender Import bleibt kompatibel und läuft über denselben Pfad.
- **Abnahmekriterien:** 1. Vorschau schreibt nichts. 2. Aktivierung atomar (eine Transaktion). 3. Gleichzeitige Aktivierung zweier Versionen: genau eine gewinnt, die andere erhält Konfliktfehler (optimistische Sperre über erwartete Vorgängerversion).

### E02.06 – Konfigurationshistorie und Vergleich
- **Priorität:** P2 · **Status:** done · **Abhängig von:** E02.05 · **Aufwand:** S
- **Ergebnis:** `GET /api/automation/trader/config` (Historie mit Autor, Zeit, Notiz, seit E02.05) und `GET …/config/diff?from_version=&to_version=`: jede abweichende Einstellung zweier Versionen mit Erklärung; unbekannte Version 404. Tests: Smoke.
- **Ziel:** Liste der Versionen mit Autor, Zeit, Notiz; Diff zweier beliebiger Versionen.

### E02.07 – Rollback
- **Priorität:** P2 · **Status:** done · **Abhängig von:** E02.06 · **Aufwand:** S
- **Ergebnis:**
  - `POST …/config/rollback` mit `version` und `expected_version` aktiviert den Inhalt einer älteren Version als neue Version (`created_by = rollback`); die Historie bleibt linear.
  - Geprüft wird streng wie beim Import: Eine Version, die heutige Regeln ablehnen, wird mit Fehlerliste abgelehnt (422). Bei zwischenzeitlicher Änderung kommt 409.
  - Läuft unter der Rundensperre und wird als Ereignis `trader-config` mit allen Änderungen protokolliert.
  - Tests: Smoke (Rollback, Einstellungsseite, Konflikt, ungültige alte Version).
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
