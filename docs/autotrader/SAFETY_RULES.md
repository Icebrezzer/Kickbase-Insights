# Sicherheitsregeln Auto-Trader 3.0

Diese Regeln gelten für jedes Arbeitspaket, jede Konfiguration und jedes Lernverfahren. Keine Konfiguration, kein Profil, kein Feature Flag und kein Lernmodus kann sie aufheben. Ein Verstoß ist ein Blocker, kein Kompromiss.

## 1. Harte Regeln (nicht konfigurierbar)

| Nr. | Regel | Heute durchgesetzt durch |
|---|---|---|
| S1 | Keine Überschreitung tatsächlicher Kickbase-Limits (33-%-Regel, Kader, Verein, Gebotsschritt) | `risk._bid` (`OVER_BUDGET`, `SQUAD_FULL`, `CLUB_FULL`, `BID_INVALID`) |
| S2 | Keine doppelte Anrechnung von Kapital oder Verkaufserlösen. Jeder Spieler ist höchstens einmal Sicherheit, und nur für einen Finanzierungsplan | Liquidation einmal je Spieler; ab E04 ein gemeinsames Sicherheiten-Register |
| S3 | Geplante und unbestätigte Verkaufserlöse sind kein Bargeld | `risk` (Verkäufe bringen in der Runde nichts), `received_known` |
| S4 | Hypothetische Neuzugänge sind keine Kaderspieler: zählen nie als Ersatz, Starter oder bestätigte Sicherheit | `pick_sale` nur auf `own`; ab E04.04/05 nur als **bedingte** Tilgung mit eigenem Stressabschlag |
| S5 | Keine automatische Wiederholung ungeklärter Schreibzugriffe; unbekannter Status wird zuerst geklärt | `_settle`, `UNCONFIRMED_ACTION`, Client ohne Retry für Writes |
| S6 | Keine Verkäufe geschützter Spieler ohne ausdrückliche Regel (Startelf-Sperre, frische Käufe, letzter Ersatz, neue Lücke) | `risk._sell` |
| S7 | Manuelle Gebote werden nie verändert oder zurückgezogen | `MANUAL_BID`, Höhenvergleich vor Rückzug |
| S8 | Keine parallele Handelsausführung (je Nutzer/Liga, prozessübergreifend) | Sperre je Nutzer/Liga, Leader-Lease `automation-leader` |
| S9 | Vor jeder Live-Aktion: Schalter, Kader, Budget, Markt neu lesen und neu planen | `_revalidate`, Kill-Switch-Neulesen |
| S10 | Punkteberechtigung zum Spieltagsbeginn hat Vorrang vor Gewinn | Phasen `repay`/`final`, Rettungsverkäufe, Rückzug eigener Gebote |
| S11 | Keine Vermischung Demo/Produktion, keine Datenvermischung zwischen Nutzern oder Ligen | `demo.db` erzwungen, `user_id`/`league_id` in jeder Abfrage |
| S12 | Schattenmodelle, Simulationen, Backtests und Lernverfahren rufen **keine schreibenden** Kickbase-Endpunkte auf und lösen **keine zusätzlichen** Lese-Aufrufe pro Runde aus | Architektur: Schatten laufen nur auf bereits geladenen Daten (Prüftest ab E03.01) |
| S13 | Keine Ausführung beliebigen Codes aus Konfigurationen oder Regeln. Das Regelwerk (E08.01) ist eine geschlossene, validierte Datenstruktur | Schema-Validierung, Whitelist von Bedingungen/Aktionen |
| S14 | Keine ungeprüfte automatische Strategieaktivierung. Ein Challenger ersetzt nie automatisch den Champion; autonome Parameteränderungen nur für freigegebene Parameter in Grenzen (E10.05) | Lernmodus, Freigabe-Liste, Grenzen |
| S15 | Keine echten Kickbase-Transaktionen in Entwicklung und Tests | MockTransport, DemoWorld, Probelauf; Agentenregel in `AGENTS.md` |
| S16 | Keine Veröffentlichung von Zugangsdaten, Tokens, echten IDs | Export ohne Tokens; Agentenregel |
| S17 | Prognosen sind keine garantierten Einnahmen. Freigaben basieren nie allein auf dem optimistischen Szenario | ab E04.03: Freigabe auf dem pessimistischen Szenario |
| S18 | Bei fehlenden oder unvollständigen Daten: konservativ bewerten oder blockieren (Fail-Closed) | bisheriges Prinzip, wird je Paket geprüft |

## 2. Verhältnis Konfiguration ↔ Sicherheit

- Die Risk Engine (`core/risk.py`) bleibt **unabhängig von der Strategie**: Sie bekommt Konfigurationswerte, aber ihre Prüfungen selbst sind Code, nicht Konfiguration.
- Jeder konfigurierbare Parameter hat **harte Grenzen im Code** (`OPTION_LIMITS`, ab E02 im Schema). Ein Import außerhalb der Grenzen wird **abgelehnt** (nicht still geklemmt), die Vorschau zeigt den Grund.
- Kreditauslastung bis 100 % des tatsächlich verfügbaren Maximalgebots ist **zulässig, nie erzwungen**; die Freigabe hängt am pessimistischen Deadline-Kontostand ≥ Reserve.

## 3. Freigabestufen neuer Handelsfunktionen

`off` (installiert, aus) → `shadow` (rechnet parallel, beeinflusst nichts) → `dry_run` (plant, sendet nichts) → `live` (nur nach ausdrücklicher Freigabe je Liga).
Standard für jede neue Funktion: `off`. Ein Wechsel nach `live` braucht eine Bestätigung im UI und wird als Ereignis protokolliert. Der bestehende Liga-Schalter „Live handeln“ bleibt zusätzlich notwendig.

## 4. Prüfpflicht je Arbeitspaket

Jedes Paket mit Einfluss auf Handel beantwortet in seiner Datei:
1. Welche Regeln S1–S18 sind berührt?
2. Wie zeigt ein Test, dass sie weiter gelten (insbesondere S2, S3, S4, S12)?
3. Was passiert bei deaktiviertem Flag (muss dem alten Verhalten entsprechen)?
