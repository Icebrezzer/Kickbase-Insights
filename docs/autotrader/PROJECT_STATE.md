# Projektstatus Auto-Trader 3.0

**Zuletzt aktualisiert:** 27.11.2026 · **Branch:** `codex/autotrader-3` (lokal, nicht gepusht) · **Basis:** `4b85715` (`codex/autotrader-2-audit`, CI grün)

## Kurzfassung

- **Erledigt:**
  - **E00** (Projektvorbereitung)
  - **E01.01** (Exporte analysiert)
  - **E01.00** (Debug-Liquidation)
  - **E01.04** (Maximalgebot gegen freigegebenes Budget, nur Backend)
- Handelsentscheidungen sind **unverändert**.
- **Nächstes Paket:** **E01.02** (einheitliche Ablehnungscodes). Parallel möglich: **E06.04** (Auswertung der Verkaufsquoten).
- **Wartet auf den Auftraggeber:**
  - die echte Sofortverkaufsquote bei Kickbase (KI-26);
  - die fachliche Entscheidung zu E05.08 (Upgrade bei Formationswechsel, KI-27).

## Ergebnis der Export-Analyse (Details `KNOWN_ISSUES.md` B)

In der Liga ohne Käufe gibt es drei Ursachen, und keine davon ist in erster Linie die Kreditberechnung:
1. **Verkaufsquote 0,9 (unverifiziert):** Kein steigender Spieler war in 2 Tagen netto positiv. Die Gewinnschwelle liegt bei über 11 % Anstieg in 2 Updates, der Median der Prognosen bei 3 %.
2. **Qualitätsvergleich über Positionen:** 162 von 307 abgelehnten Elf-Verbesserungen fallen darunter.
3. **Reserve (2 Mio.) über dem Kontostand** und `credit_mode` 1: Der Gewinnhandel hat kein Geld.

## Commits auf `codex/autotrader-3`

| Commit | Paket |
|---|---|
| `ac0bb18` | E00 Projektvorbereitung, Smoke-Test-Korrektur |
| `2e6f6ce` | E01.01 Export-Analyse |
| `263bfa0` | E01.00 Debug-Liquidation |
| `5a180be` | E01.04 `money_check` |

## Testlage (27.11.2026, lokal Windows/Python 3.12)

Volle Backend-Suite 15/15 grün: Ruff, 12 Skripte aus der CI, Migration gegen `ebf50d3` und Export-Analyse. `check_trader_safety` hat jetzt 1479 Checks. Frontend und ui-audit wurden **nicht lokal ausgeführt** (kein Node). Die CI ist für diese Commits **noch nicht gelaufen** (nicht gepusht).

## Epic-Status

| Epic | Status | Nächster Schritt |
|---|---|---|
| E00 | done | – |
| E01 | in_progress: .00, .01 und .04 done | E01.02, dann E01.03, E01.05 (UI), E01.06 |
| E02 | ready | E02.01 |
| E03 | todo | wartet auf E01.02, E02.04 |
| E04 | todo | nach E05.08 (ADR-011); wartet auf E01.04 ✓, E02.08 |
| E05 | E05.08 neu (P1) | fachliche Entscheidung, dann nach E02.08 |
| E06–E11 | todo | siehe Matrix; E06.04 jederzeit |

## Offene Entscheidungen beim Auftraggeber

1. **Sofortverkaufsquote bei Kickbase:** Wie viel Prozent des Marktwerts bringt ein Direktverkauf an Kickbase tatsächlich?
2. **E05.08:** Darf ein Upgrade, das die Formation wechselt, statt am Qualitätswert des verdrängten Spielers anderer Position an den nächsten 3 Spielen gemessen werden?
3. MASTERPLAN §7, weitere Punkte: Risikobereitschaft, Ersatzbank-Standard, globales Lernen, Release-Rhythmus und Tag-Pinning, SQLite oder PostgreSQL.

## Für die nächste KI

1. `AGENTS.md` lesen, dann dieses Dokument, dann `workpackages/E01-diagnose.md` → E01.02.
2. Lokal: `py -3.12 -m venv`, `pip install ./backend ruff`, Tests wie in `AGENTS.md` §4.
3. Nichts pushen ohne Auftrag (jeder Push baut ein Image).
4. Nach jedem Paket: Eintrag im Paket (Ergebnis, Commit), diese Datei, `CHANGELOG.md`.
