# E00 – Projektvorbereitung

Alle Pakete am 27.11.2026 bearbeitet, Branch `codex/autotrader-3` (von `codex/autotrader-2-audit` @ `4b85715`).

### E00.01 – Aktuellsten Branch und Codezustand verifizieren
- **Priorität:** P1 · **Status:** done · **Abhängig von:** – · **Aufwand:** S
- **Ergebnis:** `git fetch --all`: `origin/codex/autotrader-2-audit` = lokaler HEAD = `4b85715` (keine neueren Commits). Einziger neuerer Remote-Stand: `origin/ui-audit` (`609ed9e`, 25.11.) – von CI erzeugte Screenshots des Commits `4b85715`, kein Code. `origin/main` (`48efcfc`) ist vollständig in HEAD enthalten (55 Commits voraus). CI-Lauf „Build“ für `4b85715`: erfolgreich (25.11., 22:43 UTC, öffentliche GitHub-API).

### E00.02 – Architektur und Module analysieren
- **Status:** done · **Ergebnis:** `ARCHITECTURE.md` Teil 1. Kern: reine Logik in `core/trader.py`, `core/risk.py`; Ablauf in `sync/trader.py::_plan` (~450 Zeilen).

### E00.03 – Vorhandene Tests und CI prüfen
- **Status:** done
- **Ergebnis (lokal, Windows 11, Python 3.12 venv, SQLite):**

  | Prüfung | Ergebnis |
  |---|---|
  | `ruff check --extend-ignore E501 .` | bestanden |
  | `check_coach`, `check_trader` | bestanden |
  | `check_trader_safety` | 969 bestanden |
  | `check_trader_intelligence` / `_learning` / `_backtest` | 29 / 53 / 19 bestanden |
  | `check_audit_regressions` | bestanden |
  | `check_league_preferences`, `check_wealth`, `check_locks`, `check_leader` | bestanden |
  | `smoke_manager_tools` | **zunächst fehlgeschlagen** („negative balance before the deadline: no bids, rescue only“), Ursache: tageszeitabhängiger Test (KI-19). Nach Korrektur bestanden |
  | `check_trader_migration` gegen `ebf50d3` | bestanden (nicht in CI, KI-20) |
  | Frontend `npm run build`, `npm test` | **nicht ausgeführt** (kein Node lokal); in CI für `4b85715` bestanden |
  | CI-Umgebung Python 3.13/Linux | **nicht lokal ausgeführt** |
- **Commit:** E00-Commit (Testkorrektur `backend/tests/smoke_manager_tools.py`).

### E00.04 – Projektstruktur und KI-Arbeitsanweisungen
- **Status:** done · **Ergebnis:** `AGENTS.md`, `CHANGELOG.md`, `docs/autotrader/*`, `workpackages/`.

### E00.05 – Sicherheitsregeln dokumentieren
- **Status:** done · **Ergebnis:** `SAFETY_RULES.md` (S1–S18, Freigabestufen, Prüfpflicht).

### E00.06 – Arbeitspakete mit Abhängigkeiten und Abnahmekriterien
- **Status:** done · **Ergebnis:** `workpackages/E01–E11`, Matrix in `MASTERPLAN.md`.

### E00.07 – Release- und Rollback-Strategie
- **Status:** done · **Ergebnis:** `RELEASE_CHECKLIST.md`, ADR-009.

### E00.08 – Analyse realer JSON-Exporte vorbereiten (zusätzlich)
- **Status:** done · **Ergebnis:** `tools/autotrader/analyze_export.py` (nur Standardbibliothek, liest nur die Datei) mit `check_analyze_export.py`; am Demo-Export geprüft. Anleitung in `MASTERPLAN.md` §6.
