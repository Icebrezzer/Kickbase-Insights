# Bekannte Probleme und verifizierte Schwachstellen

Stand: 27.11.2026, Code-Stand `4b85715` (Branch `codex/autotrader-2-audit`), geprüft für E00.
Jeder Eintrag nennt die Code-Stelle. **Verifiziert** = im Code bestätigt. **Hypothese** = plausibel, braucht reale Exporte (E01.01).

Status: `offen` · `geplant (WP)` · `behoben (Commit)`.

## A. Abgleich der Übergabe-Schwachstellen mit dem Code

### 5.1 Kreditberechnung

| ID | Aussage der Übergabe | Befund | Code | Status |
|---|---|---|---|---|
| KI-01 | Neuzugänge zählen nicht als bedingte Tilgung | **Verifiziert.** `liquidation_value` sieht nur den bestätigten Kader (`own`), Docstring: „open bids are no collateral“. Bewusste 2.0-Entscheidung (Sicherheit), aber ohne bedingten Plan | `core/trader.py:363`, `sync/trader.py:792` | **umgesetzt** hinter Flags (E04.04/E04.05) |
| KI-02 | Gewinnspieler sichern ihre Finanzierung nicht ab | **Verifiziert, schärfer als beschrieben.** Mit `credit_mode = 1` (Standard) bekommt ein Gewinn-Gebot **gar keinen** Kredit; mit `credit_mode = 2` nur in Phase `normal`. Bei Kontostand ≈ 0 ist Gewinnhandel damit faktisch aus | `core/risk.py:78-87` | **umgesetzt** hinter Flag `conditional_repayment` (E04.04) |
| KI-03 | Verdrängte Stammspieler finanzieren Upgrades nicht | **Verifiziert.** Liquidation und `pick_sale` überspringen jeden fitten Spieler der besten Elf, also auch den, den das Ziel verdrängt | `core/trader.py:373`, `core/trader.py:243` | **umgesetzt** hinter Flag `upgrade_financing` (E04.05); braucht automatische Aufstellung |
| KI-04 | Liquidation nur mit den Verkäufen des laufenden Tages | **Verifiziert.** Kredit nutzt `sales_left` (heute übrig). Zusätzlich **Diagnosefehler:** Das Debug-Feld `liquidation` rechnet mit `opts.daily_sales` (vollem Limit) und dem Kader vor Ausstiegsverkäufen – Debug-Wert und tatsächlich verwendeter Wert können abweichen | `sync/trader.py:792` vs. `:979` | Diagnose **behoben** (E01.00); Logik geplant E04.02 |
| KI-05 | Ersatzschutz blockiert viel Kapital | **Verifiziert.** (a) `keeps_cover` schützt den letzten fitten Ersatz jeder Position in der Liquidation; (b) jedes Gewinn-Gebot hält `cover_max_price` je fehlender Ersatzposition zurück; (c) jede weitere Startelf-Lücke hält `cover_max_price` zurück; (d) bei Lücken in der Elf gibt es gar keine Gewinn-/Ersatzgebote | `core/trader.py:204,373`, `sync/trader.py:896-903` | geplant E05.02/E05.06 |
| KI-06 | Maximalgebot ≠ internes Budget | **Verifiziert.** `analytics.max_bid` wird in der Planung nicht berechnet, nicht protokolliert und nicht angezeigt. Die Differenz ist nirgends sichtbar | `core/analytics.py:597`, `sync/trader.py:976-992` | **behoben** im Backend (E01.04, `money_check`); Anzeige E01.05 |

### 5.2 Starre Parameter

| ID | Befund | Code | Status |
|---|---|---|---|
| KI-07 | **Verifiziert.** 20 Optionen je Liga sind einstellbar, aber ~25 strategische Konstanten sind fest: `PROFIT_HOLD=2`, `REGRET_DAYS=3`, `REBUY_BLOCK=7 d`, `MIN_HOLD=20 h`, `ROOM_EXTRA=0,6`, `SAFE_SELL_RATIO=0,9`, `PREPARE_BEFORE=24 h`, `FINAL_BEFORE=60 min`, `AVERAGE_WEIGHT=0,6`, `THIN_*`, `TURN_SHARE`, `MIN_AUCTIONS=8`, `BID_GRID=40`, `LEAGUE_PRIOR=10`, `MIN_SAMPLES=10`, `SHADOW_WEIGHT=0,5`, `SHADOWS_PER_ROUND=5`, Preisklassen, Lernraten, Prognosepause 0,3/0,45 | `core/trader.py:32-42,281-284,396-397,474,534-592`, `sync/trader.py:69-81` | geplant E02 |
| KI-08 | **Verifiziert (teilweise).** Import: unbekannte Optionsschlüssel werden verworfen und in der API-Antwort als `ignored` gemeldet; **Werte außerhalb der Grenzen werden still geklemmt**, ohne Meldung. Keine Versionierung, keine Vorschau beim Import (nur bei Profilen), keine Historie außer dem Ereignis `trader-import` | `core/trader.py:74-94`, `sync/trader.py:1141` | geplant E02.01/E02.02/E02.05 |

### 5.3 Lernen aus entgangenen Chancen

| ID | Befund | Code | Status |
|---|---|---|---|
| KI-09 | **Verifiziert.** Schattentransfers entstehen nur für **Gewinnhandels-Kandidaten** (`profit`/`near`), höchstens 5 je Runde. Abgelehnte Startelf-, Ersatz-, Budget-, Kader- und Vereinslimit-Kandidaten werden nie beobachtet | `sync/trader.py:856-884` | geplant E03.02/E03.03 |
| KI-10 | **Verifiziert.** Schatten speichern keinen Entscheidungs-Snapshot (Kontostand, Kredit, Ablehnungsgrund-Code, Konfigurations-/Modellversion), nur Gebot, Wert, Prognose | `db/models.py:430` | geplant E03.01 |
| KI-11 | **Verifiziert.** Nur eine Gebotsvariante und ein Horizont (2 Updates) je Schatten; Papier-Verkauf nur 3 Updates nach echten Verkäufen | `sync/trader.py:463-536` | geplant E03.04/E03.05 |

### 5.4 Weitere Einschränkungen

| ID | Befund | Code | Status |
|---|---|---|---|
| KI-12 | **Verifiziert.** Verkaufsquote `min(gelernt, 0,9)`. Die gelernte Quote ist der **Median aller Sofortverkäufe aller Nutzer und Ligen**, ohne Mindeststichprobe (ein Verkauf genügt) und ohne Liga-Trennung. Dieselbe Quote dient Rendite und Risiko | `core/learning.py:264`, `sync/learning.py:300`, `sync/trader.py:580` | geplant E06.04 |
| KI-13 | **Verifiziert.** Mindestmarge (`min_margin`, gelernt 50 Tsd.–1,5 Mio., global) **und** Mindestrendite gelten beide; die gelernte Marge kann nach Verlusten bis 1,5 Mio. steigen und blockiert dann fast jeden Gewinnhandel | `core/trader.py:437`, `core/trader.py:696` | Diagnose E01.03, Prüfung E06 |
| KI-14 | **Verifiziert.** Ablehnungsgründe sind deutsche Freitexte, teils kombiniert: „Marge unter der Mindestmarge oder Budget zu knapp“, „Budget oder Preis je Punkt passt nicht“. Nur die Risk Engine hat Codes | `sync/trader.py:842-850,908-912` | **behoben** (E01.02, `core/reasons.py`) |
| KI-15 | **Verifiziert.** Prognosepause ist **global** (alle Ligen), nicht ligaweise | `core/trader.py:596ff`, `sync/trader.py:837` | geplant E10 |
| KI-16 | **Verifiziert.** Opportunitätskosten: Kapitalrotation nur über den Platz-Verkauf (`swap_edge`, nur Prognose-Vergleich je Tag), keine Rendite pro Kapital und Zeit über Positionen hinweg | `core/trader.py:227-249` | geplant E06.02/E06.03 |
| KI-17 | **Verifiziert.** Keine Saison- oder Mannschaftswertabhängigkeit; Strategieprofile sind statisch | `core/trader.py:101-113` | geplant E08 |
| KI-18 | **Verifiziert.** Keine Portfolio-Simulation; Backtest nur für Gewinnhandel, alle Strategien sehen dieselben Auktionen | `core/backtest.py` | geplant E09 |

## B. Liga ohne Kaufvorschläge – Ergebnis E01.01 (27.11.2026)

Datengrundlage: zwei Exporte vom 27.11.2026, je ca. 2 Tage (25.11. 16:27 – 27.11. 19:31 UTC).
- **Liga A:** Probelauf, Gewinnhandel an, 60 Runden, **0 Gebote**.
- **Liga B:** live, 62 Runden, 22 Gebote, davon 4 gewonnen.

Beide Ligen nutzen dieselben, gegenüber dem Standard deutlich strengeren Einstellungen: `min_gain` 10, `min_play` 80 %, `min_avg_edge` 15 %, `reserve` 2 Mio., `profit_share` 35 %, `min_roi` 3 %. Ausgewertet mit `analyze_export.py` und einer Nachrechnung der letzten Runden mit `core/trader.py` (Skripte nicht im Repo, nur Rohdaten-Auswertung).

**Ursache 1 – Gewinnhandel ist mit der Verkaufsquote 0,9 rechnerisch fast unmöglich (KI-26, belegt).**
- Netto beim Mindestgebot war in **keiner** Runde für **keinen** steigenden, fitten Spieler positiv: Liga A 0 von 32, Liga B 0 von 27.
- Der beste Wert lag bei −0,11 Mio. (A) bzw. −0,06 Mio. (B).
- Mit 0,9 muss ein Spieler in 2 Updates um mehr als 11,1 % plus Gebotsaufschlag steigen. Die Prognosen lagen im Median bei 3,0 % (A) bzw. 1,3 % (B), höchstens bei 11,4 %.
- Alle 526 Ablehnungen „Marge oder Budget“ in Liga A scheitern **an beidem**. Mehr Kredit allein hätte also **keinen einzigen** Gewinnkauf ausgelöst.
- Die 0,9 ist eine **nicht verifizierte Annahme** (`AUTOTRADER.md` §11). Echte Verkäufe zur Kalibrierung gibt es in keinem der beiden Exporte.

**Ursache 2 – Startelf-Upgrades scheitern am Qualitätsvergleich über Positionen hinweg (KI-27, belegt).**
- In Liga A gab es 307 mögliche Elf-Verbesserungen (Spieler-Runden mit positivem Punktgewinn). Sie wurden abgelehnt wegen:
  - 162 (8 Spieler): Qualität, **verdrängter Spieler auf anderer Position**;
  - 58: Qualität, gleiche Position;
  - 51: `min_gain` 10;
  - 35: Einsatzquote unter 80 %.
- Nur eine einzige Verbesserung bestand alle Filter.
- Beispiel aus der letzten Runde: Ein Verteidiger (+23,5 erwartete Punkte) stellt die Formation von 3-5-2 auf 4-4-2 um und verdrängt einen Stürmer. Dessen erwartete Punkte sind niedriger (73,3), seine Qualität aber höher (151 gegen 101). Die Ablehnung erfolgt, weil `lineup_upgrade` den Verdrängten nimmt, wenn es keinen Spieler gleicher Position gibt (`core/trader.py:319-327`), und Qualitäten verschiedener Positionen vergleicht.
- Ob diese Ablehnung fachlich gewollt ist, muss der Auftraggeber entscheiden (Schutz vor Einmal-Effekten oder ein Fehler).

**Ursache 3 – Bargeld ist durch die Reserve negativ (belegt, verschärfend).**
- In Liga A lag der Kontostand zwischen −12,98 und +2,82 Mio., die Reserve bei 2 Mio. `cash_free` war deshalb in jeder Runde negativ (−21,3 bis −1,5 Mio.).
- Mit `credit_mode = 1` bekommt der Gewinnhandel dann kein Geld (KI-02). Freigegeben waren zuletzt 11,4 Mio. für Startelf/Ersatz und −1,5 Mio. für Gewinnhandel – bei einem Maximalgebot von 84,4 Mio.

**Hypothesen aus E00:**

| # | Hypothese | Ergebnis |
|---|---|---|
| 1 | `credit_mode 1` + Kontostand ≈ 0 | **bestätigt, aber nicht allein ursächlich** (Ursache 1 blockiert zuerst) |
| 2 | Lücken in der Elf | widerlegt für A (`gaps` 0); in B wirksam (113× „erst die Startelf füllen“), dort aber gewollt |
| 3 | `min_margin` hoch / Prognosepause | widerlegt (150.000 Standard, keine Pause, aber auch keine Prognose-Kalibrierung: `gain_samples` 0) |
| 4 | Stop-Loss | widerlegt |
| 5 | Unklarer Aufruf | widerlegt (A hat keine Trades) |
| 6 | Kader voll | teilweise (76× in A, nicht dominierend) |
| 7 | Upgrade-Filter | **bestätigt** (Ursache 2; zusätzlich `min_gain` 10 und `min_play` 80 %) |
| 8 | Schalter | widerlegt (Trader an, Gewinnhandel an) |

**Liga B, Nebenbefunde:**
- Am 25.11. um 12:17/13:48 gab es 13 Gebote mit „+1.0xx Punkten“. Das war der Lücken-Strafwert einer älteren Version (vor `4b85715`); alle diese Gebote sind `expired`. Seit 17:13 bietet der Trader plausibel auf Lücken.
- Ein gewonnenes Gebot steht mit `paid` 15,80 Mio. bei einem Gebot von 15,28 Mio. im Log. `paid` kommt bei fehlendem Wert aus dem Kickbase-Kaufpreis; die Ursache ist nicht geklärt (KI-28).

## C. Qualität, Tests, Doku

| ID | Befund | Status |
|---|---|---|
| KI-19 | `smoke_manager_tools.py` war **tageszeitabhängig**: Die Rettungsprüfung lief bei „Deadline − 2 h“, die Phase `repay` beginnt aber erst nach dem letzten Marktwert-Update (22:15 Berlin). Die Demo-Deadline wandert mit der Uhr; am 27.11. lag „− 2 h“ in `prepare` → Test schlug lokal fehl, obwohl CI am 25.11. grün war | **behoben** (E00.03): Test nutzt `repay_from(deadline) + 1 min` und prüft die Phase |
| KI-20 | `check_trader_migration.py` braucht den Backend-Ordner einer alten Version als Argument und läuft **nicht in CI** | offen (E11.06) |
| KI-21 | `AUTOTRADER.md` §3.1 („nach 10 Min. → failed“) und §12 (Rundensperre nur je Prozess) sind durch Audit Nr. 33/34 veraltet | offen (E00-Folge, bei nächster Änderung an AUTOTRADER.md) |
| KI-22 | `AUDIT-2026-11-25.md` sagt „nicht gepusht, [skip ci]“; der Branch ist inzwischen gepusht und CI lief für `4b85715` erfolgreich (25.11., 22:43 UTC) | Hinweis, kein Handlungsbedarf |
| KI-23 | Lokale Prüfumgebung hat kein Node → Frontend-Build/-Tests nur in CI | Hinweis |
| KI-24 | Jeder Push auf irgendeinen Branch baut und veröffentlicht ein Image (`type=ref,event=branch`, `type=sha`). Vorschau-Images entstehen damit automatisch; `latest` nur von `main` | Hinweis für Release-Strategie |
| KI-26 | Sofortverkaufsquote 0,9 ist unverifiziert und bestimmt allein, ob Gewinnhandel möglich ist (siehe B, Ursache 1). Sie wirkt auch auf Liquidation, Kredit und Startelf-Preis je Punkt | **geklärt:** Kickbase zahlt 100 % (Nutzer, 27.11.). Option `sell_ratio` je Liga, Standard 90 – zum Aktivieren 100 setzen. Auswertung echter Verkäufe weiter E06.04 |
| KI-27 | `lineup_upgrade` vergleicht bei einem Formationswechsel die Qualität mit einem Spieler anderer Position (siehe B, Ursache 2) | **umgesetzt** (E05.08): Option `upgrade_cross_position`, Standard aus |
| KI-28 | `paid` > Gebot bei einem gewonnenen Gebot in Liga B | offen, beobachten |
| KI-25 | Aus dem Audit übernommen: Backend-Abhängigkeiten nur mit Mindestversionen, PostgreSQL-Pfad ungetestet, keine Freigabe für mehrere Replikate, keine Freigabe für unbeaufsichtigten Live-Betrieb | offen (E11) |
