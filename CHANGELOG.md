# Changelog

Format angelehnt an [Keep a Changelog](https://keepachangelog.com/de/1.1.0/). Auto-Trader-3.0-Einträge nennen die Paket-ID (`docs/autotrader/workpackages/`). Frühere Stände: `AUTOTRADER_RELEASE.md` (Auto-Trader 2.0) und `AUDIT-2026-11-25.md`.

## [Unveröffentlicht] – Auto-Trader 3.0

### Hinzugefügt
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
