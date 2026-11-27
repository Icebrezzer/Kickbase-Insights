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

Stand nach der Auswertung der realen Exporte (§9, ADR-011, ADR-012). ✅ = erledigt.

| Rang | Paket | N | R | A | Score | Welle | Änderung durch die Daten |
|---:|---|---:|---:|---:|---:|---|---|
| ✅ | E01.01 Exporte analysieren | 5 | 1 | 1 | 8 | W1 | – |
| ✅ | E01.00 Debug-Liquidation | 3 | 1 | 1 | 4 | W1 | – |
| ✅ | E01.04 Maximalgebot vs. internes Budget | 5 | 1 | 1 | 8 | W1 | – |
| ✅ | E06.00 Verkaufsquote als Liga-Option | 5 | 2 | 1 | 7 | W1 | **neu**: Hauptursache in Liga A |
| ✅ | E05.08 Formationswechsel nach Punkten | 5 | 2 | 1 | 7 | W1 | **neu**: 162 von 307 Ablehnungen |
| ✅ | E01.02 Einheitliche Ablehnungscodes | 5 | 1 | 2 | 7 | W1 | – |
| ✅ | **E10.00 Prognose-Kalibrierung aus allen beobachteten Spielern** | 5 | 1 | 2 | 7 | **W1 (neu)** | Prognose trifft die Richtung zu 94–99 %, wurde aber nie kalibriert |
| ✅ | E01.03 Statistik abgelehnter Kandidaten | 3 | 1 | 1 | 4 | W2 | – |
| ✅ | E02.01 Schema | 4 | 1 | 2 | 5 | W2 | – |
| ✅ | E02.02 Validierung | 4 | 1 | 1 | 6 | W2 | – |
| ✅ | E02.08 Feature Flags | 5 | 2 | 1 | 7 | W2 | `sell_ratio` und `upgrade_cross_position` bleiben Optionen (begründet in E02.08) |
| ✅ | E01.05 Diagnoseansicht UI | 4 | 1 | 2 | 5 | W2 | – |
| 8 | E02.03 / E02.04 Speicherung, Übernahme ohne Neustart | 4 | 2–3 | 2 | 4 | W3 | – |
| 9 | E03.01 / E03.02 Snapshots, alle Ablehnungen | 5 | 2 | 2 | 6 | W3 | – |
| 10 | **E05.02 Konfigurierbare Ersatzbank** | 5 | 3 | 2 | 5 | **W4 (vorgezogen)** | Ersatzschutz bindet in Liga A ≈ 20 von 34,5 Mio. Bankwert |
| 11 | E04.01 Finanzmodul (identisch) | 3 | 2 | 1 | 3 | W4 | – |
| 12 | E04.03 Szenarien | 5 | 2 | 2 | 6 | W4 | Stressparameter aus E10.00 statt geschätzt |
| 13 | E04.05 Upgrade-Finanzierung (verdrängter Starter) | 5 | 4 | 2 | 4 | W4 | Hebel bei kleiner Bank |
| 14 | E04.04 Gewinnspieler als bedingte Tilgung | 5 | 4 | 2 | 4 | W4 | einziger Kredithebel in Liga B |
| 15 | E04.06 + E04.10 Gemeinsame Finanzierung, Risk Engine | 5 | 3 | 2 | 5 | W4 | – |
| 16 | E04.02 Mehrtägige Liquidation | **3** | 3 | 2 | **1** | **W5 (zurückgestuft)** | bringt in beiden Ligen 0 €: Kaderschutz bindet, nicht die Verkaufslimits |
| 17 | E01.06 Was-wäre-wenn | 4 | 1 | 2 | 5 | W5 | – |
| – | E06.04 Verkaufsquoten auswerten | 2 | 1 | 1 | 2 | W6 | nur noch Kontrolle, Quote ist bekannt (100 %) |
| – | Rest (E02.05–09, E03.03–09, E04.07–09/11, E05–E11) | | | | | W5–W8 | nach Matrix |

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

**Kritischer Pfad bis zum Kern-Nutzen (Kredit bis Maximalgebot), nach §9 angepasst:** E01.04 ✅ → E10.00 → E02.01 → E02.02 → E02.08 → E05.02 → E04.01 → E04.03 → E04.05/E04.04 → E04.06 → E04.10. Die mehrtägige Liquidation (E04.02) liegt nicht mehr auf dem kritischen Pfad. E02.03/E02.04 (Speicherung, Hot Reload) und E03.01 laufen parallel und sind für E04.04 (Schattenmessung vor Live) nötig.

**Parallelisierbar** (keine gemeinsamen Dateien/Migrationen): E06.04 (`sync/learning.py`) ∥ E01.02 (`sync/trader.py`, `core/reasons.py`) – nicht parallel mit E01.00/E01.04 (gleiche Stellen in `sync/trader.py`). Migrationen (E02.03, E03.01, E09.01) **nie parallel** (eine Schema-Version je Paket).

## 5. Release-Strategie: früh und klein

| Welle | Inhalt | Verhalten ändert sich? | Release |
|---|---|---|---|
| W1 | E01.00 ✅, E01.04 ✅, E06.00 ✅, E05.08 ✅, E01.02, E10.00 | nein ohne Einschalten (neue Optionen Standard aus, E10.00 nur Messung) | `3.2.0` sobald W1 komplett, Preview vorher über Branch-Image |
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

1. ~~Exporte~~ – erhalten am 27.11.2026, ausgewertet (§9). **Neuer Export in etwa 14 Tagen** zur Bestätigung.
1a. ~~Sofortverkaufsquote~~ – **geklärt:** 100 % des Marktwerts. ~~Formationswechsel~~ – **geklärt:** nach Punkten bewerten.
2. **Kickbase-Regeln:** Gilt die 33-%-Regel auf Teamwert nach Abzug offener Gebote? Wird ein negativer Kontostand zum Anpfiff exakt zum ersten Anpfiff geprüft oder zur Deadline (`AUTOTRADER.md` §11)? Ist das Verkaufslimit je Tag ein Kickbase-Limit oder nur eine Trader-Einstellung? (Plan geht von Letzterem aus.)
3. **Risikobereitschaft:** Welcher pessimistische Deadline-Kontostand ist akzeptabel (Vorschlag: ≥ 0 bei −3 % Marktwert je Update und Quote 0,85)?
4. **Mehrbenutzer:** Wie viele Nutzer/Ligen laufen produktiv (für Ressourcenschätzung E03.08/E09)?
5. **Ersatzbank:** Gewünschter Standard für neue Ligen – weiter volle Absicherung?
6. **Lernen über Nutzer hinweg:** Dürfen Prognose-Kalibrierung, Marge und Verkaufsquote weiterhin global (alle Nutzer) gelernt werden, oder je Nutzer/Liga getrennt?
7. **Release-Rhythmus:** Darf jede Welle sofort auf `main` (→ `latest`, TrueNAS), oder soll TrueNAS einen festen Versions-Tag nutzen (empfohlen, `RELEASE_CHECKLIST.md`)?
8. **PostgreSQL:** Läuft produktiv SQLite oder PostgreSQL? (PostgreSQL-Pfad ist ungetestet, KI-25.)

## 8. Änderungen gegenüber der Übergabe

Siehe `DECISIONS.md` ADR-008: E01.00 neu, E02.08 vorgezogen, E01.01 bis Datenlage blockiert, E06.04 (nur Auswertung) in Welle 1 vorgezogen, Migrationstest in CI unter E11.06.

## 9. Erkenntnisse aus den realen Exporten (27.11.2026)

Grundlage sind zwei Exporte mit je etwa 2 Tagen Rundendaten (60 bzw. 62 Runden, 73 bzw. 41 Tageswechsel von Marktwerten). **Die Stichprobe ist klein.** Die Zahlen leiten die Reihenfolge, sie kalibrieren noch keine Parameter. Eine Wiederholung mit einem Export über ≥ 14 Tage ist eingeplant. Details: `KNOWN_ISSUES.md` B.

### 9.1 Kaufblockaden

| Befund | Liga A (keine Käufe) | Liga B (live) | Folge |
|---|---|---|---|
| Gewinnkandidaten netto positiv beim Mindestgebot, Quote 90 % → 100 % | 0 → 8 | 0 → 4 | E06.00 ✅. Kickbase zahlt 100 % (Auftraggeber) |
| Startelf-Upgrades ohne → mit Formationsregel | 1 → 8 | 8 → 8 | E05.08 ✅ |
| Gewinnhandel bekommt Geld | nein: Reserve 2 Mio. > Kontostand, `credit_mode` 1 | ja, wenig (frei 4 Mio.) | Strategieentscheidung des Nutzers; `money_check` zeigt es |

### 9.2 Finanzierung (E04)

| Messung (letzte Runde) | Liga A | Liga B |
|---|---|---|
| Kreditrahmen nach Kickbase (33 % Teamwert) | 83,9 Mio. | 54,2 Mio. |
| Liquidation = tatsächlicher Kredit (Quote 90 → 100 %) | 12,9 → 14,4 Mio. | 0 → 0 |
| … mit allen Verkäufen bis zur Deadline statt nur heute | unverändert 14,4 Mio. | unverändert 0 |
| Bankwert gesamt / davon durch Ersatzschutz gesperrt | 34,5 / ≈ 20,1 Mio. (letzter TW, letzter MF, zweiter ST) | 20,7 / 20,7 Mio. (einziger Ersatz-TW, einziger Ersatz-MF) |
| Kader | 15 Spieler, 11 in der Elf | 11 Spieler, Elf mit 2 Lücken |

**Folgerungen:**
1. **Nicht die Verkaufslimits begrenzen den Kredit, sondern der Kaderschutz.** Die mehrtägige Liquidation (E04.02) bringt in beiden Ligen 0 €. Sie wird zurückgestuft.
2. **Der größte Hebel ist die Ersatzbank (E05.02).** In Liga A gibt sie bis zu 20 Mio. frei, wenn Ersatz außerhalb kritischer Phasen nicht vollständig gehalten werden muss. Sie wird vor die Finanzierungspakete gezogen.
3. **Bei kleiner Bank finanzieren nur bedingte Pläne.** Das sind der verdrängte Starter (E04.05) und das Ziel selbst als Gewinnspieler (E04.04). In Liga B ist das der einzige Weg zu Kredit.
4. **Stressszenario (E04.03) aus den Daten:** Der Prognosefehler je Update (tatsächlich − Prognose, in % des Werts) lag bei p5 −1,5 % (A) bzw. −1,0 % (B), im schlechtesten Fall −3,8 % bzw. −3,5 %. Tagesänderungen insgesamt reichten bis −12 % bzw. −19 %, dann aber bei fallender Prognose.
   - **Startwert pessimistisch:** steigende Prognose − 2 % je Update, fallende Prognose − 4 % je Update, Quote 100 %.
   - Nachkalibrierung mit E10.00 auf ≥ 14 Tagen.

### 9.3 Lernen (E10)

| Messung | Liga A | Liga B |
|---|---|---|
| Richtung des nächsten Updates richtig prognostiziert | 66 / 67 (99 %) | 33 / 35 (94 %); streng gezählt, unveränderter Wert = Fehler (E10.00): 32 / 35 (91 %) |
| Tatsächlich / prognostiziert bei steigender Prognose | 0,90 | 0,99 |
| Mittlerer absoluter Fehler je Update | 0,32 % des Werts | 0,39 % des Werts |
| Kalibrierte Prognosen im Trader-Modell (`gain_samples`) | **0** | **0** |
| Schattentransfers | 15 (alle `near`, 2 gewonnen) | 9 (alle `near`) |

**Folgerungen:**
1. **Das Lernsystem nutzt fast keine der verfügbaren Daten.** Die Prognose-Kalibrierung lernt nur aus eigenen Käufen und Schatten mit einem Horizont von 2 Updates. Jede Runde liegen aber Prognose und späterer Marktwert für **alle** Markt- und Kaderspieler vor, etwa 30–70 Beobachtungen am Tag statt 0.
   - **E10.00 (neu, P1):** Kalibrierung (`gain_ratio`, Trefferquote, Fehlerverteilung) aus diesen Beobachtungen.
   - Das geht ohne zusätzliche Kickbase-Aufrufe (S12) und ohne Zukunftswissen: Die Prognose wird zum Entscheidungszeitpunkt gespeichert und mit dem **späteren** Wert verglichen.
2. **Ohne Kalibrierung ist jede Finanzierung blind.** E04.03 bezieht seine Stressparameter aus E10.00, deshalb steht E10.00 vor E04.
3. **Schattentransfers lernten mit falscher Quote.** Mit 0,9 wurde fast jeder Papier-Kauf zum Verlust; das treibt die globale Mindestmarge nach oben. Seit E06.00 rechnen sie mit der Quote ihres Besitzers. Ob die gelernte `min_margin` (aktuell 150.000 = Startwert) schon verzerrt ist, prüft E10.01.
4. **Mindeststichprobe plus Mindestdauer:** Bei 30–70 Beobachtungen am Tag ist `MIN_SAMPLES` = 10 schon nach einem Tag erreicht. Parameteränderungen (E10.03) brauchen deshalb zusätzlich mindestens 14 Tage Daten, damit ein einzelner Markttrend nicht als Modellqualität gilt.

### 9.4 Leitlinien für die Finanzierungs- und Lernlogik

- Erst messen (E10.00, E01.02), dann finanzieren (E05.02 → E04).
- Jede Finanzierungsfunktion wird gegen beide Ligaprofile getestet: große Bank ohne Geld (A) und kleine Bank mit Lücken (B). Beide kommen als anonymisierte Testfälle aus den Exporten in `check_trader_finance.py`.
- Neuer Export in etwa 14 Tagen (nach Release W1/W2), um §9 zu bestätigen oder zu korrigieren.
