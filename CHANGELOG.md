# Changelog

Format angelehnt an [Keep a Changelog](https://keepachangelog.com/de/1.1.0/). Auto-Trader-3.0-Einträge nennen die Paket-ID (`docs/autotrader/workpackages/`). Frühere Stände: `AUTOTRADER_RELEASE.md` (Auto-Trader 2.0) und `AUDIT-2026-11-25.md`.

## [Unveröffentlicht] – Auto-Trader 3.0

### Hinzugefügt
- E00: Projektstruktur für Auto-Trader 3.0 – `AGENTS.md`, `docs/autotrader/` (Masterplan, Architektur, Projektstatus, Entscheidungen, Konfigurationsschema-Entwurf, Sicherheitsregeln, Testmatrix, Release-Checkliste, bekannte Probleme, Arbeitspakete E00–E11).
- E00.08: `tools/autotrader/analyze_export.py` – Offline-Analyse eines Trader-Exports (Maximalgebot vs. freigegebenes Budget, Ablehnungsgründe als provisorische Codes, Schalter, gelernte Werte), mit Prüfskript `check_analyze_export.py` in der CI.

### Behoben
- E00.03: `backend/tests/smoke_manager_tools.py` prüfte die Rettung vor dem Spieltag zu einer festen Zeit („Deadline − 2 h“), die je nach Uhrzeit der Demo-Deadline noch in der Phase `prepare` lag; der Test schlug dann fehl. Er nutzt jetzt den Beginn der Tilgungsphase.

### Verhalten
- Keine Änderung am Handelsverhalten.

## [3.1.0] – 25.11.2026
- Auto-Trader 2.0 und Audit, siehe `AUTOTRADER_RELEASE.md` und `AUDIT-2026-11-25.md`.
