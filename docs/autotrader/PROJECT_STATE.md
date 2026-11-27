# Projektstatus Auto-Trader 3.0

**Zuletzt aktualisiert:** 27.11.2026 · **Branch:** `codex/autotrader-3` (lokal, nicht gepusht) · **Basis:** `4b85715` (`codex/autotrader-2-audit`, CI grün)

## Kurzfassung

- **Erledigt:**
  - **E00** (Projektvorbereitung)
  - **E01.01** (Exporte analysiert)
  - **E01.00** (Debug-Liquidation)
  - **E01.04** (Maximalgebot gegen freigegebenes Budget, nur Backend)
  - **E06.00** (Verkaufsquote als Liga-Option)
  - **E05.08** (Formationswechsel nach Punkten)
- Ohne geänderte Einstellungen handelt der Trader **wie bisher**. Die neuen Optionen `sell_ratio` (Standard 90) und `upgrade_cross_position` (Standard aus) wirken erst nach dem Einschalten je Liga.
- **Nächstes Paket:** **E01.02** (einheitliche Ablehnungscodes). Parallel möglich: **E06.04** (Auswertung der Verkaufsquoten).
- **Geklärt (27.11.2026):** Kickbase zahlt beim Sofortverkauf 100 % des Marktwerts. Formationswechsel mit mehr Punkten sind erwünscht.

## Ergebnis der Export-Analyse (Details `KNOWN_ISSUES.md` B)

In der Liga ohne Käufe gibt es drei Ursachen, und keine davon ist in erster Linie die Kreditberechnung:
1. **Verkaufsquote 0,9** (inzwischen geklärt: Kickbase zahlt 100 %, Option `sell_ratio`): Kein steigender Spieler war in 2 Tagen netto positiv. Die Gewinnschwelle liegt bei über 11 % Anstieg in 2 Updates, der Median der Prognosen bei 3 %.
2. **Qualitätsvergleich über Positionen:** 162 von 307 abgelehnten Elf-Verbesserungen fallen darunter.
3. **Reserve (2 Mio.) über dem Kontostand** und `credit_mode` 1: Der Gewinnhandel hat kein Geld.

## Commits auf `codex/autotrader-3`

| Commit | Paket |
|---|---|
| `ac0bb18` | E00 Projektvorbereitung, Smoke-Test-Korrektur |
| `2e6f6ce` | E01.01 Export-Analyse |
| `263bfa0` | E01.00 Debug-Liquidation |
| `5a180be` | E01.04 `money_check` |
| `6c0bc16` | E06.00 `sell_ratio`, E05.08 `upgrade_cross_position` |

## Testlage (27.11.2026, lokal Windows/Python 3.12)

Volle Backend-Suite 15/15 grün: Ruff, 12 Skripte aus der CI, Migration gegen `ebf50d3` und Export-Analyse. `check_trader_safety` hat jetzt 1494 Checks. Frontend und ui-audit wurden **nicht lokal ausgeführt** (kein Node). Die CI ist für diese Commits **noch nicht gelaufen** (nicht gepusht).

## Epic-Status

| Epic | Status | Nächster Schritt |
|---|---|---|
| E00 | done | – |
| E01 | in_progress: .00, .01 und .04 done | E01.02, dann E01.03, E01.05 (UI), E01.06 |
| E02 | ready | E02.01 |
| E03 | todo | wartet auf E01.02, E02.04 |
| E04 | todo | wartet auf E02.08 (E01.04 ✓, E05.08 ✓) |
| E05 | E05.08 done (als Liga-Option) | E05.02 nach E02.04 |
| E06–E11 | todo | siehe Matrix; E06.04 jederzeit |

## Offene Entscheidungen beim Auftraggeber

1. MASTERPLAN §7, weitere Punkte: Risikobereitschaft, Ersatzbank-Standard, globales Lernen, Release-Rhythmus und Tag-Pinning, SQLite oder PostgreSQL.

## Für die nächste KI

1. `AGENTS.md` lesen, dann dieses Dokument, dann `workpackages/E01-diagnose.md` → E01.02.
2. Lokal: `py -3.12 -m venv`, `pip install ./backend ruff`, Tests wie in `AGENTS.md` §4.
3. Nichts pushen ohne Auftrag (jeder Push baut ein Image).
4. Nach jedem Paket: Eintrag im Paket (Ergebnis, Commit), diese Datei, `CHANGELOG.md`.
