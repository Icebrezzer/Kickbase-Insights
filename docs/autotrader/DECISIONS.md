# Architekturentscheidungen (ADR)

Format: Kontext · Entscheidung · Folgen. Neue Einträge unten anhängen, alte nie löschen (nur `ersetzt durch ADR-x`).

## ADR-001 – Erweitern statt neu schreiben (27.11.2026, angenommen)
**Kontext:** 2.0 ist produktiv, hat ~1.100 Regressionstests und ein Audit. `sync/trader.py::_plan` ist mit ~450 Zeilen groß.
**Entscheidung:** Keine Neuentwicklung. Neue Logik als reine Funktionen in `core/*`, `_plan` ruft sie auf. `_plan` wird nur dort zerlegt, wo ein Paket es braucht.
**Folgen:** Kleine, testbare Pakete; bestehende Tests bleiben Sicherheitsnetz.

## ADR-002 – Feature Flags vor jeder Verhaltensänderung (27.11.2026, angenommen)
**Kontext:** Neue Finanzierungs- und Handelslogik darf nicht automatisch produktiv werden.
**Entscheidung:** Ein minimales Flag-System (E02.08) wird **vor** E04 gebaut. Stufen `off | shadow | dry_run | live`, je Liga, Standard `off`. Bei `off` ist das Verhalten identisch mit 2.0 (Test: gleiche Aktionen auf denselben Eingaben).
**Folgen:** E02.08 wird gegenüber der Roadmap vorgezogen (direkt nach E02.01/E02.02).

## ADR-003 – Konfiguration versioniert in der Datenbank (27.11.2026, angenommen)
**Kontext:** Strategieänderungen sollen ohne Image-Build wirken. Heute: `userautomation.trader_options` (JSON, unversioniert).
**Entscheidung:** Neue Tabelle `strategyconfig` (append-only: `league_id`, `user_id`, `version`, `schema_version`, `data`, `created_at`, `created_by`, `active`, `note`). Aktivierung = atomarer Wechsel des `active`-Zeigers. Jede Runde lädt die aktive Version **einmal** am Anfang und schreibt `config_version` ins Debug-Protokoll und in jeden TradeLog-/Snapshot-Eintrag. `trader_options` bleibt als Rückfall und wird bei der Migration als Version 1 übernommen.
**Folgen:** Hot Reload ohne Neustart; Rollback = alte Version aktivieren; Änderungen mitten in einer Runde wirken erst in der nächsten.

## ADR-004 – Unbekannte/ungültige Importwerte werden abgelehnt, nicht geklemmt (27.11.2026, angenommen)
**Kontext:** `Options.load` klemmt still (KI-08). Für gespeicherte Altdaten ist das richtig (Robustheit), für Importe nicht (Nutzer merkt es nicht).
**Entscheidung:** Zwei Pfade: `load` (tolerant, für gespeicherte Daten, unverändert) und `validate` (streng, für Import/UI: liefert Fehlerliste, nichts wird übernommen, solange Fehler bestehen).

## ADR-005 – Finanzierung auf dem pessimistischen Szenario (27.11.2026, vorgeschlagen)
**Kontext:** Kredit soll bis zum Maximalgebot nutzbar sein, Prognosen sind unsicher.
**Entscheidung:** `core/finance.py` berechnet optimistisch/realistisch/pessimistisch. **Freigabe nur, wenn der pessimistische Deadline-Kontostand ≥ Reserve** ist, mit mehrtägiger Liquidation (Verkäufe je verbleibendem Tag, Sperrenablauf) und einem Sicherheiten-Register (jeder Spieler höchstens einmal). Bedingte Tilgung (Gewinnspieler, verdrängter Starter) nur mit eigenem Abschlag und nur, wenn der Plan **auch beim Verlust der Auktion** aufgeht oder die Abhängigkeit explizit ist („Verkauf erst nach bestätigtem Zuschlag“).
**Offen:** Stressparameter (Abschlag je Update, Quote pessimistisch) werden mit E06.04 empirisch bestimmt; bis dahin konservative Startwerte.

## ADR-006 – Schatten nur aus geladenen Daten (27.11.2026, angenommen)
**Entscheidung:** Snapshots, Schatten, Portfolios und Lernen lesen nie zusätzlich von Kickbase und schreiben nie. Durchgesetzt durch Architektur (keine Client-Referenz in `core/shadow.py`, `core/portfolio.py`) und einen Test mit einem Mock-Client, der jeden Aufruf zählt.

## ADR-007 – Mehrere Gebotsvarianten = eine Stichprobe (27.11.2026, angenommen)
**Entscheidung:** Ein Snapshot je Auktion (`league_id`, `player_id`, `listed_at`) und Nutzer; Gebotsvarianten und Verkaufsstrategien sind Unterergebnisse dieses Snapshots. Lerngewicht je Auktion insgesamt ≤ dem bisherigen Schattengewicht 0,5.

## ADR-008 – Reihenfolge der Roadmap leicht angepasst (27.11.2026, angenommen)
**Änderungen gegenüber der Übergabe:**
1. **E01.00 neu:** Diagnose-Korrektur „Debug-Liquidation ≠ verwendete Liquidation“ (KI-04) – winzig, sofortiger Nutzen.
2. **E02.08 Feature Flags** vor E02.03–E02.07 (ADR-002).
3. **E01.01 (Exporte)** ist blockiert, bis Exporte vorliegen; E01.02–E01.04 laufen vorher, damit die Exporte danach aussagekräftiger sind (ein frischer Export **nach** E01.02/04 enthält Codes und Budgetvergleich).
4. **E11.06** übernimmt `check_trader_migration.py` in CI (KI-20).
**Begründung:** Abhängigkeiten und unmittelbarer Nutzen; keine inhaltliche Streichung.

## ADR-009 – Versionierung (27.11.2026, angenommen)
**Kontext:** App-Version `3.1.0` (`core/version.py`, `pyproject.toml`), Images `3.1.0-mgr.<run>`, Tags `latest` (main), `<branch>`, `sha-<kurz>`.
**Entscheidung:** App-Version bleibt das Versionsschema; Auto-Trader-3.0-Pakete erscheinen im `CHANGELOG.md` mit Paket-ID. Erste veröffentlichte AT3-Funktion hebt die Version auf `3.2.0`. Strategiekonfiguration hat ein eigenes `schema_version` (beginnend bei 1), Modellzustand behält `MODEL_VERSION` (2).

## ADR-010 – Neue Tabellen ohne Erhöhung der Schema-Version (27.11.2026, angenommen)
**Kontext:** `init_db` bricht ab, wenn die gespeicherte Schema-Version **höher** ist als die des Codes (`db/__init__.py`). Jede Erhöhung von `SCHEMA_VERSION` macht damit ein Image-Rollback ohne Backup unmöglich.
**Entscheidung:** AT3-Tabellen (`strategyconfig`, `decisionsnapshot`, Portfolios) entstehen additiv per `create_all`, neue Spalten über `_LATER_COLUMNS`, Datenübernahmen idempotent beim Start. `SCHEMA_VERSION` wird nur bei nicht additiven Änderungen erhöht – dann mit Backup-Pflicht und ausdrücklichem Hinweis im Release.
**Folgen:** Ältere Images starten weiter auf einer AT3-Datenbank und ignorieren neue Tabellen. Neue Spalten in bestehenden Tabellen brauchen einen Standardwert, damit ältere Images Zeilen weiter schreiben können.

## ADR-011 – Prioritäten nach Auswertung der Exporte (27.11.2026, angenommen)
**Kontext:** E01.01 zeigt: In der Liga ohne Käufe verhindert die angenommene Sofortverkaufsquote 0,9 jeden Gewinnhandel, und ein Qualitätsvergleich über Positionen verhindert fast alle Startelf-Upgrades. Kredit ist nicht die primäre Ursache (KNOWN_ISSUES B).
**Entscheidung:**
1. **Kickbase-Verkaufsquote klären** (Frage an den Auftraggeber) hat Vorrang vor E04. E06.04 (Auswertung echter Verkäufe) bleibt in Welle 1.
2. **E05.08 neu, P1**, direkt nach E02.08: Formationswechsel-Upgrade hinter Flag.
3. E04 (Finanzierung) bleibt wichtig, kommt aber nach E05.08. Ohne korrekte Verkaufsquote würden auch Liquidation und bedingte Tilgung mit einem falschen Wert rechnen.
4. E01.00 und E01.04 laufen unverändert als Nächstes (Diagnose ohne Verhaltensänderung).

## ADR-012 – Messen vor Finanzieren (27.11.2026, angenommen)
**Kontext:** Die Exporte zeigen dreierlei (MASTERPLAN §9):
- Der Kredit wird durch den Kaderschutz begrenzt, nicht durch die Verkaufslimits.
- Die Prognose ist in kurzen Zeiträumen sehr treffsicher, wurde aber nie kalibriert.
- Schatten lernten mit einer falschen Verkaufsquote.

**Entscheidung:**
1. **E10.00** (Prognose-Kalibrierung aus allen beobachteten Spielern) kommt in Welle 1.
2. **E05.02** (Ersatzbank) kommt vor E04.
3. **E04.03** bekommt seine Stressparameter aus E10.00. Bis dahin gelten die Startwerte aus §9.2.
4. **E04.02** wird auf P2 zurückgestuft.
5. Lernparameter ändern sich erst nach mindestens 14 Tagen Daten.

**Folgen:** Der kritische Pfad zur Kreditnutzung verlängert sich um E10.00 und E05.02. Dafür rechnet die Finanzierung mit gemessenen statt geschätzten Risiken. E04.02 bleibt geplant, falls spätere Exporte bindende Verkaufslimits zeigen.
