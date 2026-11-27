# Masterplan Auto-Trader 3.0 – Adaptive Intelligence

Stand: 27.11.2026 · Ausgangscode `4b85715` · Arbeitsbranch `codex/autotrader-3`

## 1. Ziel

Langfristig maximaler sportlicher Erfolg durch effiziente Kapitalnutzung. **Leitprinzip: maximale sinnvolle Kapitalnutzung bei kontrolliertem Risiko und zuverlässiger Punkteberechtigung zum Spieltagsbeginn.** Bewertet wird realisierter finanzieller und sportlicher Mehrwert, nicht Transferzahl oder theoretischer Marktwertgewinn.

Nicht verhandelbar: `SAFETY_RULES.md`. Bestehende Daten, Einstellungen, Lernwerte und Transfers bleiben erhalten.

## 2. Epics

| Epic | Thema | Pakete | Kern-Nutzen | Datei |
|---|---|---:|---|---|
| E00 | Projektvorbereitung | 8 | Grundlage | `workpackages/E00-projektvorbereitung.md` |
| E01 | Diagnose und Transparenz | 7 | „Warum kauft er nicht?“ sichtbar | `E01-diagnose.md` |
| E02 | Configuration Engine + Feature Flags | 9 | Strategie ohne Image-Build | `E02-configuration-engine.md` |
| E03 | Shadow Intelligence 2.0 | 9 | Lernen ohne eigene Transfers | `E03-shadow-intelligence.md` |
| E04 | Financial Intelligence | 11 | Kredit bis zum Maximalgebot, abgesichert | `E04-financial-intelligence.md` |
| E05 | Squad Intelligence | 7 | Rollen, flexible Ersatzbank | `E05-squad-intelligence.md` |
| E06 | Trading Intelligence | 7 | Opportunitätskosten, Rotation | `E06-E08-trading-auction-strategy.md` |
| E07 | Auction Intelligence | 5 | bessere Gebote | `E06-E08-trading-auction-strategy.md` |
| E08 | Strategy Intelligence | 5 | Regelwerk, Saisonphase | `E06-E08-trading-auction-strategy.md` |
| E09 | Shadow Portfolios | 7 | Champion-Challenger | `E09-E11-portfolios-learning-qa.md` |
| E10 | Adaptive Learning | 8 | kontrolliertes Selbstlernen | `E09-E11-portfolios-learning-qa.md` |
| E11 | Übergreifende QS | 8 | Abschlussprüfung | `E09-E11-portfolios-learning-qa.md` |

## 3. Priorisierung

Bewertung je Paket: **Nutzen** (N, 1–5), **Risiko** für Handel/Daten (R, 1 = gering … 5 = hoch), **Aufwand** (A, S=1, M=2). Score = N × 2 − R − A. Reihenfolge = Abhängigkeiten zuerst, dann Score.

| Rang | Paket | N | R | A | Score | Welle |
|---:|---|---:|---:|---:|---:|---|
| 1 | E01.00 Debug-Liquidation korrigieren | 3 | 1 | 1 | 4 | W1 |
| 2 | E01.04 Maximalgebot vs. internes Budget | 5 | 1 | 1 | 8 | W1 |
| 3 | E01.02 Einheitliche Ablehnungscodes | 5 | 1 | 2 | 7 | W1 |
| 4 | E06.04 Verkaufsquoten auswerten (nur Anzeige) | 4 | 1 | 1 | 6 | W1 |
| 5 | E01.01 Exporte analysieren (blockiert) | 5 | 1 | 1 | 8 | W1 (sobald Daten da) |
| 6 | E01.03 Statistik abgelehnter Kandidaten | 3 | 1 | 1 | 4 | W2 |
| 7 | E02.01 Schema | 4 | 1 | 2 | 5 | W2 |
| 8 | E02.02 Validierung | 4 | 1 | 1 | 6 | W2 |
| 9 | E02.08 Feature Flags | 5 | 2 | 1 | 7 | W2 |
| 10 | E01.05 Diagnoseansicht UI | 4 | 1 | 2 | 5 | W2 |
| 11 | E02.03 Liga-Konfiguration speichern (Migration) | 4 | 3 | 2 | 3 | W3 |
| 12 | E02.04 Übernahme ohne Neustart | 4 | 2 | 1 | 5 | W3 |
| 13 | E02.05 Import mit Vorschau | 4 | 2 | 2 | 4 | W3 |
| 14 | E03.01 Entscheidungs-Snapshots | 5 | 2 | 2 | 6 | W3 |
| 15 | E03.02 Alle Ablehnungen erfassen | 4 | 1 | 1 | 6 | W3 |
| 16 | E04.01 Finanzmodul (identisch) | 3 | 2 | 1 | 3 | W4 |
| 17 | E04.02 Mehrtägige Liquidation | 5 | 3 | 2 | 5 | W4 |
| 18 | E04.03 Szenarien | 5 | 2 | 2 | 6 | W4 |
| 19 | E04.04 Gewinnspieler als bedingte Tilgung | 5 | 4 | 2 | 4 | W4 |
| 20 | E04.05 Upgrade-Finanzierung | 5 | 4 | 2 | 4 | W4 |
| 21 | E04.06 Gemeinsame Finanzierung | 4 | 3 | 2 | 3 | W4 |
| 22 | E04.10 Risk-Engine-Integration | 5 | 2 | 1 | 7 | W4 (mit E04.06) |
| 23 | E05.02 Konfigurierbare Ersatzbank | 4 | 3 | 2 | 3 | W5 |
| 24 | E01.06 Was-wäre-wenn | 4 | 1 | 2 | 5 | W5 |
| – | Rest (E02.06/07/09, E03.03–09, E04.07–09/11, E05–E11) | | | | | W5–W8 nach Matrix |

## 4. Abhängigkeitsmatrix (Kernpfad)

Zeile hängt von Spalte ab (●). Vollständige Abhängigkeiten stehen in jedem Paket.

| ↓ hängt ab von → | E01.00 | E01.02 | E01.04 | E02.01 | E02.02 | E02.08 | E02.03 | E02.04 | E03.01 | E04.01 | E04.02 | E04.03 | E04.06 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| E01.03 | | ● | | | | | | | | | | | |
| E01.04 | ● | | | | | | | | | | | | |
| E01.05 | | ● | ● | | | | | | | | | | |
| E01.06 | | ● | | | ● | | | | | | | | |
| E02.02 | | | | ● | | | | | | | | | |
| E02.08 | | | | | ● | | | | | | | | |
| E02.03 | | | | | | ● | | | | | | | |
| E02.04 | | | | | | | ● | | | | | | |
| E03.01 | | ● | | | | | | ● | | | | | |
| E04.01 | | | ● | | | ● | | | | | | | |
| E04.02 | | | | | | | | | | ● | | | |
| E04.03 | | | | | | | | | | | ● | | |
| E04.04 | | | | | | | | | ● | | | ● | |
| E04.05 | | | | | | | | | | | | ● | |
| E04.06 | | | | | | | | | | | | ● | |
| E04.10 | | | | | | | | | | | | | ● |
| E05.02 | | | | | | | | ● | | | | | |
| E06.03 | | | | | | | | | | | | | ● |
| E09.01 | | | | | | | | | ● | | | | ● |

**Kritischer Pfad bis zum Kern-Nutzen (Kredit bis Maximalgebot):** E01.00 → E01.04 → E02.01 → E02.02 → E02.08 → E04.01 → E04.02 → E04.03 → E04.04/E04.05 → E04.06 → E04.10. E02.03/E02.04 (Speicherung, Hot Reload) und E03.01 laufen parallel und sind für E04.04 (Schattenmessung vor Live) nötig.

**Parallelisierbar** (keine gemeinsamen Dateien/Migrationen): E06.04 (`sync/learning.py`) ∥ E01.02 (`sync/trader.py`, `core/reasons.py`) – nicht parallel mit E01.00/E01.04 (gleiche Stellen in `sync/trader.py`). Migrationen (E02.03, E03.01, E09.01) **nie parallel** (eine Schema-Version je Paket).

## 5. Release-Strategie: früh und klein

| Welle | Inhalt | Verhalten ändert sich? | Release |
|---|---|---|---|
| W1 | E01.00, E01.04, E01.02, E06.04 | nein (nur Diagnose) | `3.2.0` sobald W1 komplett, Preview vorher über Branch-Image |
| W2 | E01.03, E02.01, E02.02, E02.08, E01.05 | nein (Flags existieren, alle `off`) | `3.2.x` |
| W3 | E02.03, E02.04, E02.05, E03.01, E03.02 | nein für Handel; neue Tabellen additiv (ADR-010), Backup trotzdem | `3.3.0` |
| W4 | E04.01–E04.06, E04.10 | **ja, nur bei Flag ≠ off**; zuerst `shadow` je Liga ≥ 2 Spieltage, dann `dry_run`, dann `live` einer Testliga | `3.4.0` |
| W5+ | E05.02, E01.06, E04.07–09, E06, E07, E08, E09, E10 | je Flag | je Paket |

Einzelne fertige Pakete dürfen sofort veröffentlicht werden; Wellen sind Orientierung, keine Sperre. Details: `RELEASE_CHECKLIST.md`.

## 6. Analyse der realen JSON-Exporte (E01.01) – Vorbereitung

**Vom Auftraggeber benötigt** (je Liga, besonders die ohne Kaufvorschläge, plus mindestens eine Vergleichsliga):
1. `GET /api/automation/trader/export?days=21` (enthält Einstellungen, gelernte Werte, Trades, Schatten, Ereignisse, Debug-Runden; keine Tokens).
2. Kurze Angaben: Wurde in der Liga manuell gehandelt? Ist „Gewinnhandel“ an? Live oder Probelauf? Auto-Aufstellung an?
3. Idealerweise ein zweiter Export **nach** Release W1 (enthält dann Reason Codes und Budgetvergleich).

**Ablauf:**
```
python -I tools/autotrader/analyze_export.py liga-a.json liga-b.json
python -I tools/autotrader/analyze_export.py liga-a.json --json > analyse.json
```
Exporte außerhalb des Repos ablegen (oder unter `exports/`, per `.gitignore` ausgeschlossen). Ergebnisse nur anonymisiert dokumentieren.

**Prüfreihenfolge:** Schalter → Phase → `released_profit` / `released_lineup` vs. `max_bid` (Differenz, Kreditmodus) → `gaps_*` → `slots` → Pausen (`paused`, `forecast_paused`) → `min_margin` gelernt → Gründe-Histogramm → `risk_blocked` → unklare Aufrufe (`trades` mit `pending`/`unknown`).

## 7. Offene Fragen an den Auftraggeber

1. **Exporte** (siehe §6) – Blocker für E01.01.
2. **Kickbase-Regeln:** Gilt die 33-%-Regel auf Teamwert nach Abzug offener Gebote? Wird ein negativer Kontostand zum Anpfiff exakt zum ersten Anpfiff geprüft oder zur Deadline (`AUTOTRADER.md` §11)? Ist das Verkaufslimit je Tag ein Kickbase-Limit oder nur eine Trader-Einstellung? (Plan geht von Letzterem aus.)
3. **Risikobereitschaft:** Welcher pessimistische Deadline-Kontostand ist akzeptabel (Vorschlag: ≥ 0 bei −3 % Marktwert je Update und Quote 0,85)?
4. **Mehrbenutzer:** Wie viele Nutzer/Ligen laufen produktiv (für Ressourcenschätzung E03.08/E09)?
5. **Ersatzbank:** Gewünschter Standard für neue Ligen – weiter volle Absicherung?
6. **Lernen über Nutzer hinweg:** Dürfen Prognose-Kalibrierung, Marge und Verkaufsquote weiterhin global (alle Nutzer) gelernt werden, oder je Nutzer/Liga getrennt?
7. **Release-Rhythmus:** Darf jede Welle sofort auf `main` (→ `latest`, TrueNAS), oder soll TrueNAS einen festen Versions-Tag nutzen (empfohlen, `RELEASE_CHECKLIST.md`)?
8. **PostgreSQL:** Läuft produktiv SQLite oder PostgreSQL? (PostgreSQL-Pfad ist ungetestet, KI-25.)

## 8. Änderungen gegenüber der Übergabe

Siehe `DECISIONS.md` ADR-008: E01.00 neu, E02.08 vorgezogen, E01.01 bis Datenlage blockiert, E06.04 (nur Auswertung) in Welle 1 vorgezogen, Migrationstest in CI unter E11.06.
