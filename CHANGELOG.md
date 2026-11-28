# Changelog

Format angelehnt an [Keep a Changelog](https://keepachangelog.com/de/1.1.0/). Auto-Trader-3.0-Einträge nennen die Paket-ID (`docs/autotrader/workpackages/`). Frühere Stände: `AUTOTRADER_RELEASE.md` (Auto-Trader 2.0) und `AUDIT-2026-11-25.md`.

## [Unveröffentlicht] – Auto-Trader 3.0

### Hinzugefügt
- E05.02: Konfigurierbare Ersatzbank (Option „Ersatzbank“: volle Absicherung, minimal oder keine Bank zwischen den Spieltagen) hinter dem Flag `flexible_bench`. Mit „keine Bank“ steigt der Kredit in den beiden ausgewerteten Ligen von 14,4 auf 34,5 Mio. bzw. von 0 auf 20,7 Mio. Ab 24 Std. vor dem Spieltag gilt wieder volle Absicherung.
- E03.01/E03.02: Entscheidungs-Snapshots hinter dem Flag `decision_snapshots` (Standard aus). Bei eingeschaltetem Flag hält jede Runde für jede Auktion fest, was der Trader wusste und warum er (nicht) geboten hat, einmal je Auktion und ohne Kickbase-Aufruf. Grundlage für das Lernen aus verpassten Chancen.
- E02.05: Strategie-Konfiguration per API mit Vorschau importieren: `GET /api/automation/trader/config`, `POST …/config/preview` (strenge Prüfung und alle Änderungen, schreibt nichts) und `POST …/config/activate` (nur gültig und nur auf der geprüften Version, protokolliert).
- E02.03/E02.04: Die Trader-Einstellungen jeder Liga werden versioniert gespeichert (Tabelle `strategyconfig`, Version 1 aus den bisherigen Einstellungen). Jede Änderung über die Seite oder den Import ist eine neue Version. Eine Runde plant mit genau einer Version, die in Debug-Protokoll, Aktionen, Handelsprotokoll und Export steht.
- E01.05: Automatik-Seite, Karte „Autotrader jetzt“: neuer Bereich „Warum kauft der Trader – oder nicht?“ mit Maximalgebot und freigegebenem Geld samt benannten Abzügen, den häufigsten Ablehnungsgründen der letzten 7 Tage und der Prognosegüte.
- E02.08: Feature Flags je Liga für neue Handelsfunktionen (`off`, `shadow`, `dry_run`, `live`; Standard `off`), API `GET`/`PUT /api/automation/trader/flags`. `live` nur mit Bestätigung und bei eingeschaltetem Live-Handel; jede Änderung wird protokolliert.
- E02.02: Strenge Validierung von Strategie-Konfigurationen (`strategy_config.validate`). Unbekannte oder ungültige Werte werden mit Pfad und Grund abgelehnt, nichts wird teilweise übernommen; alte 2.0-Optionen werden erkannt.
- E02.01: Versioniertes Strategie-Konfigurationsschema v1 (`core/strategy_config.py`, `GET /api/automation/trader/schema`): alle Liga-Optionen und die festen Regeln mit Pfad, Typ, Einheit, Grenzen, Standardwert und Erklärung.
- E01.03: Statistik der abgelehnten Kandidaten über 1, 7 und 21 Tage (`rejections` im Dashboard-API): geprüfte Spieler, Spieler mit Gebot und häufigste Haupt- und Nebengründe, je Spieler und Tag einmal gezählt.
- E10.00: Prognosegüte auf allen beobachteten Spielern. Je Liga und Marktwert-Tag wird die Prognose jedes Kader- und Marktspielers gespeichert und später mit dem echten Wert verglichen. Trefferquote, Kalibrierung und Fehlerverteilung stehen im Dashboard-API und im Export (`forecast_quality`). Neue Tabelle `forecastobservation`, ohne Änderung der Schema-Version.
- E01.02: Einheitliche Ablehnungscodes (`core/reasons.py`): Jeder Marktspieler einer Runde trägt im Debug-Protokoll und im Export einen primären und optional sekundäre Codes. Aus „Marge oder Budget“ werden die einzelnen Ursachen, etwa `MARGIN_BELOW_MIN` + `BUDGET` + `CREDIT_MODE`.
- E06.00: Neue Liga-Option **Sofortverkauf bringt (% des Marktwerts)** (`sell_ratio`, 50–100, Standard 90 wie bisher). Kickbase zahlt den vollen Marktwert; mit 100 rechnen Gewinnhandel, Kredit, Rettung, Schatten und Backtest mit dem echten Erlös.
- E05.08: Neue Liga-Option **Formationswechsel nach Punkten bewerten** (`upgrade_cross_position`, Standard aus). Ein Neuzugang, der die Formation ändert und einen Spieler anderer Position verdrängt, wird nach erwarteten Punkten (nächster Spieltag und nächste 3 Spiele) bewertet.
- E01.04: Jede Trader-Runde vergleicht das Kickbase-Maximalgebot mit dem intern freigegebenen Geld je Zweck. Jede Differenz wird mit Grund benannt (`RESERVE`, `DEBT`, `LIQUIDATION`, `CREDIT_MODE`, `PHASE`, `PROFIT_ROOM`): Feld `money_check` im Debug-Protokoll, im Export und im Dashboard-API.
- E00: Projektstruktur für Auto-Trader 3.0 – `AGENTS.md`, `docs/autotrader/` (Masterplan, Architektur, Projektstatus, Entscheidungen, Konfigurationsschema-Entwurf, Sicherheitsregeln, Testmatrix, Release-Checkliste, bekannte Probleme, Arbeitspakete E00–E11).
- E00.08: `tools/autotrader/analyze_export.py` – Offline-Analyse eines Trader-Exports (Maximalgebot vs. freigegebenes Budget, Ablehnungsgründe als provisorische Codes, Schalter, gelernte Werte), mit Prüfskript `check_analyze_export.py` in der CI.

### Behoben
- E01.00: Das Debug-Feld `liquidation` zeigte den Liquidationswert des ganzen Tageslimits, der Kredit rechnete aber mit den heute noch möglichen Verkäufen. Jetzt steht dort der tatsächlich verwendete Wert; der Tageswert steht zusätzlich in `liquidation_full_day`.
- E00.03: `backend/tests/smoke_manager_tools.py` prüfte die Rettung vor dem Spieltag zu einer festen Zeit („Deadline − 2 h“), die je nach Uhrzeit der Demo-Deadline noch in der Phase `prepare` lag; der Test schlug dann fehl. Er nutzt jetzt den Beginn der Tilgungsphase.

### Verhalten
- Ohne Änderung der Einstellungen handelt der Trader wie bisher. Beide neuen Optionen wirken erst, wenn du sie je Liga einschaltest.

## [3.1.0] – 25.11.2026
- Auto-Trader 2.0 und Audit, siehe `AUTOTRADER_RELEASE.md` und `AUDIT-2026-11-25.md`.
