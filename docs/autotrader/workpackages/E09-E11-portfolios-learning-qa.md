# E09 – Shadow Portfolios · E10 – Adaptive Learning · E11 – Übergreifende Qualitätssicherung

## E09 – Shadow Portfolios und Champion-Challenger

Voraussetzung: E03 (Snapshots, Abrechnung) und E04 (Finanzplanung als reine Funktion). Flag: `shadow_portfolios`. Ressourcengrenze: `simulation_intensity` (Anzahl Portfolios, Rundenfrequenz).

### E09.01 – Virtuelle Konten und Kader
- **Priorität:** P2 · **Abhängig von:** E03.06, E04.06 · **Aufwand:** M
- **Ziel:** Tabellen `shadowportfolio` (Konfigurationsversion, Startwerte) und `shadowposition`; Start als Kopie des echten Kaders/Kontos zu einem Zeitpunkt.
- **Abnahmekriterien:** vollständige Trennung von echten Daten (eigene Tabellen, kein Schreibzugriff auf `tradelog`); Liga-/Nutzer-Isolation.

### E09.02 – Virtuelle Transferausführung
- **Abhängig von:** E09.01 · **Aufwand:** M · **Ziel:** Dieselbe Planung (`_plan`-Kern) mit Portfolio-Zustand, Ausführung virtuell, Abrechnung über bekannte Transfers wie E03.04. **Kein Client-Objekt erreichbar** (S12, Test).

### E09.03 – Realistische Budget- und Kaderlimits
- **Abhängig von:** E09.02 · **Aufwand:** S · **Ziel:** Risk Engine prüft virtuelle Aktionen wie echte (gleiche Codes).

### E09.04 – Alternative Finanzierungsmodelle
- **Abhängig von:** E09.03 · **Aufwand:** S · **Ziel:** Portfolios mit unterschiedlichen `finance.*`-Werten (konservativ … maximale kontrollierte Kreditauslastung).

### E09.05 – Champion-Challenger-Simulation
- **Abhängig von:** E09.04 · **Aufwand:** M · **Ziel:** Kennzahlen (Nettovermögen, realisiert, Buchgewinn, erwartete Punkte, Kapitalbindung, max. Verlust, Deadline-Sicherheit, Zuschlagsquote, Umsatz, Rendite/€ und /Tag, Kaderqualität). Simulationsgrenzen ausgewiesen (Einfluss auf Auktionen und andere Manager unbekannt).

### E09.06 – Vergleich über mehrere Spieltage
- **Abhängig von:** E09.05 · **Aufwand:** S · **Ziel:** Rollierende Fenster, Konfidenzintervalle (Bootstrap über Spieltage), keine Rangfolge ohne Mindestzeitraum.

### E09.07 – Portfolio-Dashboard
- **Abhängig von:** E09.06 · **Aufwand:** M · **Priorität:** P3

## E10 – Adaptive Learning

Modi (Schema `learning.mode`): `observe` · `assisted` (Standard) · `bounded_auto`.

### E10.00 – Prognose-Kalibrierung aus allen beobachteten Spielern (neu, aus §9.3)
- **Priorität:** P1 · **Status:** done · **Abhängig von:** – · **Aufwand:** M · **Flag:** – (Messen und Anzeigen); die Nutzung der Kalibrierung in der Planung kommt später hinter ein Flag
- **Ergebnis:**
  - Neue Tabelle `forecastobservation` (additiv, ADR-010; Schlüssel Liga, Spieler, Marktwert-Tag). `TraderService._observe_forecasts` speichert bei jeder Planungsrunde die ungeskalierte Prognose (1 und 2 Updates) aller Kader-, Markt- und Gebotsspieler mit Prognose, einmal je Liga und Tag. Einmal täglich werden offene Beobachtungen gegen `MarketValueHistory` abgerechnet; nur exakte Tage zählen, Lücken bleiben unbekannt.
  - Aufbewahrung 120 Tage. Ein Fehler beim Speichern bricht keine Handelsrunde ab.
  - `core/learning.py::forecast_quality` berechnet je Horizont: Trefferquote der Richtung (ein unveränderter Wert zählt als Fehler), Kalibrierung tatsächlich/prognostiziert und Fehlerquantile p5/p50/p95/min in % des Werts, getrennt nach steigender und fallender Prognose, dazu den mittleren absoluten Fehler. Die Werte stehen in Dashboard-API und Export (`forecast_quality`).
  - Abnahme:
    1. Nachrechnung beider Exporte: Liga A 66/67 (98,5 %), Verhältnis 0,90, mittlerer Fehler 0,32 %; Liga B 32/35 (91 %, streng gezählt; §9.3 zählte 94 %), Verhältnis 0,99, mittlerer Fehler 0,39 %. Die Abweichung kommt allein aus der strengeren Zählung.
    2. Eine Beobachtung je Spieler und Tag, auch nach mehreren Runden und einem simulierten Neustart (Smoke-Test).
    3. `benchmark_audit`: Planung im Median 102,5–104,9 ms gegenüber 102,1–102,7 ms beim Ausgangsstand (≤ +2,7 %, im Rauschen), SQL-Abfragen im Median unverändert 48. Wachstum der Datenbank: etwa 30–70 Zeilen je Liga und Tag, also bei 120 Tagen höchstens etwa 8.400 Zeilen je Liga; nicht an einer echten DB gemessen.
    4. Handelsverhalten unverändert: Die Beobachtung ändert keine Entscheidung, die Suite ist grün.
  - Keine Kickbase-Aufrufe: `_observe_forecasts` bekommt keinen Client, nur bereits geladene Daten (S12).
  - Ein älteres Image (`4b85715`) startet auf der neuen Datenbank (geprüft).
  - Tests: `check_trader_forecast_quality.py` (16 Checks, in CI; Abrechnung, Lücken, Statistik, Tageswechsel 22:00 im Winter und Sommer) und Smoke-Test (Schreiben, Eindeutigkeit, Abrechnung, Liga-Trennung, Dashboard/Export).
- **Ausgangssituation:** In beiden Ligen gilt `gain_samples` = 0. Die Prognose wird nur über eigene Käufe und Schatten kalibriert, obwohl jede Runde Prognose und späteren Marktwert für 30–70 Spieler kennt. Die Messung aus den Exporten (MASTERPLAN §9.3): Richtung 94–99 % richtig, mittlerer Fehler 0,3–0,4 % je Update, p5 −1,0 bis −1,5 %.
- **Ziel:** Je Liga und global eine fortlaufende Prognose-Statistik je Horizont (1 und 2 Updates):
  - Trefferquote der Richtung;
  - tatsächlich / prognostiziert (Basis für `gain_ratio`);
  - Fehlerquantile p5, p50 und p95 in % des Werts, getrennt nach steigender und fallender Prognose sowie Preisklasse;
  - Stichprobe und Zeitraum.
- **Umfang:**
  - Neue Tabelle `forecastobservation` (additiv, ADR-010) mit `league_id`, `player_id`, `market_value_day`, `value`, `forecast_1`, `forecast_2` und `model_version`. Geschrieben wird beim ersten Sehen eines Spielers je Marktwert-Tag aus bereits geladenen Daten.
  - Die Auswertung erfolgt, sobald der Wert des Folgetags in `MarketValueHistory` steht; danach wird aggregiert.
  - Aufbewahrung 120 Tage, danach nur Aggregate.
  - Debug, Export und Dashboard zeigen die Statistik.
- **Nicht enthalten:** Änderung von `gain_ratio` oder `forecast_pause` (folgt als E10.03-Vorschlag) und Nutzung in E04.03 (dort).
- **Module:** `core/learning.py` (reine Auswertung), `sync/trader.py` oder `sync/learning.py` (Schreiben und Aggregieren), `db/models.py`, Tests.
- **Sicherheit:** S12: Ein Zähl-Mock beweist, dass es keine zusätzlichen Kickbase-Aufrufe gibt. Kein Zukunftswissen: Nur die zum Beobachtungszeitpunkt gespeicherte Prognose wird mit dem späteren Wert verglichen (Test mit veränderter Zukunft). Liga-Isolation.
- **Abnahmekriterien:**
  1. Nachgerechnete Werte für die beiden Exporte stimmen mit §9.3 überein (anonymisierte Testdaten).
  2. Eine Beobachtung je Spieler, Liga und Tag, auch bei 300 Runden.
  3. Laufzeit je Runde höchstens 5 % mehr, Wachstum der Datenbank je Liga und Monat gemessen.
  4. Das Handelsverhalten ist unverändert.
- **Pflichttests:** neue `check_trader_forecast_quality.py` (in CI): Lücken in der Historie, Spieler verschwindet vom Markt, Wechsel des Marktwert-Tags um 22:00 Berlin, Sommerzeitumstellung.
- **Migration:** neue Tabelle · **Rollback:** Schreiben abschalten (Option), Tabelle bleibt.

### E10.01 – Mindeststichproben und Lernkonfidenz
- **Priorität:** P2 · **Abhängig von:** E03.07, E10.00 · **Aufwand:** S · **Ziel:** Je gelerntem Wert: n, effektives n (gewichtet), Konfidenz **und Mindestdauer (14 Tage, §9.3)**. Werte unter der Mindeststichprobe werden angezeigt, aber nicht angewandt. Zusätzlich wird geprüft, ob die gelernte `min_margin` durch Schatten mit der alten Quote 0,9 verzerrt ist; falls ja, folgt ein Rücksetzvorschlag.

### E10.02 – Zeitlich getrennte Validierung
- **Priorität:** P2 · **Abhängig von:** E10.01 · **Aufwand:** M · **Ziel:** Walk-Forward-Trennung für alle Lernverfahren (ersetzt u. a. den Holdout „jede fünfte Zeile“ der Erwartungsgewichte, Audit-Restrisiko 4).
- **Abnahmekriterien:** Test: Zeilen desselben Spielers/Zeitraums nie gleichzeitig in Training und Validierung.

### E10.03 – Automatische Parametervorschläge
- **Priorität:** P2 · **Abhängig von:** E10.02, E03.06 · **Aufwand:** M · **Ziel:** Vorschlag (Parameter, alt→neu, erwarteter Nutzen auf Validierung, Risiko, Datengrundlage) z. B. „`min_margin` zu hoch: 23 verpasste Chancen mit Median +X“.

### E10.04 – Assistierter Lernmodus
- **Priorität:** P2 · **Abhängig von:** E10.03, E02.05 · **Aufwand:** S · **Ziel:** Vorschlag → Vorschau (E02.05) → Freigabe → neue Konfigurationsversion `created_by = "learning"`.

### E10.05 – Begrenzter autonomer Lernmodus
- **Priorität:** P3 · **Abhängig von:** E10.04, E10.07 · **Aufwand:** M · **Ziel:** Nur Parameter aus `learning.auto_parameters`, Schrittgrenze je Änderung (z. B. ±10 %), Mindeststichprobe, Abkühlzeit, Validierung gegen unveränderte Referenz.
- **Sicherheit:** S14. Harte Sicherheitsregeln und Flags sind nie `auto_parameters`.

### E10.06 – Modellversionierung
- **Priorität:** P2 · **Abhängig von:** E02.06 · **Aufwand:** S · **Ziel:** `ModelState` mit Versionshistorie (append-only), `model_version` in Snapshots und Debug.

### E10.07 – Erfolgsüberwachung und Rollback
- **Priorität:** P3 · **Abhängig von:** E10.06, E09.05 · **Aufwand:** M · **Ziel:** Nach jeder autonomen Änderung Beobachtungsfenster; Verschlechterung gegenüber Referenz über Schwelle → automatischer Rollback auf Vorversion + Push.

### E10.08 – Learning-Dashboard
- **Priorität:** P3 · **Abhängig von:** E10.03 · **Aufwand:** M

## E11 – Übergreifende Qualitätssicherung

QS läuft in jedem Paket; E11 ist die Abschlussprüfung bzw. sammelt Querschnittsaufgaben.

| ID | Titel | Priorität | Abhängig | Abnahmekriterium (Kern) |
|---|---|---|---|---|
| E11.01 | Historisches Backtesting über den ganzen Trader | P3 | E09.05 | Backtest nutzt Snapshots (E03.01) als Marktzustand; Ergebnisse je Strategie reproduzierbar (fester Seed) |
| E11.02 | Finanzielle Stresstests | P2 | E04.06 | Alle Finanzszenarien aus Übergabe §25 als automatisierte Tests in CI |
| E11.03 | Performance und Ressourcen | P2 | E03.01 | `benchmark_audit.py` je Release; Budget aus ARCHITECTURE §2.3 eingehalten; DB-Größe je Liga/Monat gemessen |
| E11.04 | Sicherheitsprüfung | P2 | E02.05 | Import-Fuzzing, Regelwerk ohne Codeausführung, Isolation, keine Tokens in Exporten |
| E11.05 | Vollständige Regressionstests | P2 | – | Alle Skripte in CI, inkl. neuer `check_trader_*` |
| E11.06 | Migration und Wiederherstellung | P1 | E02.03 | `check_trader_migration.py` in CI gegen festes Alt-Release (`git archive`), Backup/Restore-Test SQLite; PostgreSQL-Pfad mindestens in CI-Service-Container (KI-20, KI-25) |
| E11.07 | 360-Grad-UI/UX-Prüfung | P3 | E01.05 ff. | ui-audit (Chromium + WebKit) ohne Überlauf, Bedienung mobil geprüft |
| E11.08 | Abschlussdokumentation | P3 | alle | `AUTOTRADER.md` auf 3.0 aktualisiert, KI-21 behoben |
