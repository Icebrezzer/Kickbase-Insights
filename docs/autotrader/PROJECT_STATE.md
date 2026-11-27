# Projektstatus Auto-Trader 3.0

**Zuletzt aktualisiert:** 27.11.2026 · **Branch:** `codex/autotrader-3` (lokal, nicht gepusht) · **Basis:** `4b85715` (`codex/autotrader-2-audit`, CI grün)

## Kurzfassung

- **E00 Projektvorbereitung: abgeschlossen.** Doku-Struktur, Sicherheitsregeln, Masterplan, ~75 Arbeitspakete mit Abnahmekriterien, Abhängigkeitsmatrix, Release-/Rollback-Strategie, Export-Analysewerkzeug.
- Handelsverhalten ist **unverändert** (nur ein Test und Werkzeuge geändert).
- **Blocker:** E01.01 wartet auf reale JSON-Exporte (MASTERPLAN §6, Frage 1).
- **Nächstes Paket:** **E01.00** (Debug-Liquidation), dann **E01.04**, **E01.02**; parallel möglich **E06.04**.

## Verifizierte Kernbefunde (Details `KNOWN_ISSUES.md`)

1. Gewinnhandel bekommt mit `credit_mode = 1` (Standard) **keinen** Kredit – bei Kontostand ≈ 0 kauft der Trader dann nur Startelf/Ersatz (KI-02). Stärkster Kandidat für „keine Käufe“, **nicht bewiesen**.
2. Liquidation nur mit heutigen Verkäufen, ohne verdrängte Starter, ohne bedingte Neuzugänge (KI-01/03/04).
3. Maximalgebot wird in der Planung nicht berechnet und nirgends mit dem internen Budget verglichen (KI-06).
4. Debug-Feld `liquidation` weicht vom tatsächlich verwendeten Wert ab (KI-04) → E01.00.
5. Ablehnungsgründe sind kombinierte Freitexte (KI-14); Schatten nur für Gewinnhandel (KI-09).
6. Verkaufsquote global über alle Nutzer, ohne Mindeststichprobe (KI-12).

## Testlage (27.11.2026, lokal Windows/Python 3.12)

13/13 Backend-Prüfungen grün, Ruff grün, `check_analyze_export` grün. `smoke_manager_tools` war tageszeitabhängig (KI-19) → behoben. Frontend und ui-audit **nicht lokal ausgeführt** (kein Node). Details `workpackages/E00-projektvorbereitung.md`.

## Epic-Status

| Epic | Status | Nächster Schritt |
|---|---|---|
| E00 | done | – |
| E01 | ready (E01.01 blocked) | E01.00 |
| E02 | ready | E02.01 (nach W1 oder parallel zu E06.04) |
| E03 | todo | wartet auf E01.02, E02.04 |
| E04 | todo | wartet auf E01.04, E02.08 |
| E05–E11 | todo | siehe Matrix |

## Offene Entscheidungen beim Auftraggeber

MASTERPLAN §7 (Exporte, Kickbase-Regeln, Risikobereitschaft, Ersatzbank-Standard, globales Lernen, Release-Rhythmus/Tag-Pinning, SQLite vs. PostgreSQL).

## Für die nächste KI

1. `AGENTS.md` lesen, dann dieses Dokument, dann `workpackages/E01-diagnose.md` → E01.00.
2. Lokal: `py -3.12 -m venv`, `pip install ./backend ruff`, Tests wie in `AGENTS.md` §4.
3. Nichts pushen ohne Auftrag (jeder Push baut ein Image).
4. Nach jedem Paket: Eintrag im Paket (Ergebnis, Commit), diese Datei, `CHANGELOG.md`.
