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

### E10.01 – Mindeststichproben und Lernkonfidenz
- **Priorität:** P2 · **Abhängig von:** E03.07 · **Aufwand:** S · **Ziel:** Je gelerntem Wert: n, effektives n (gewichtet), Konfidenz; Werte unter Mindeststichprobe werden angezeigt, aber nicht angewandt.

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
