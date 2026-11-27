# E01 – Diagnose und Transparenz

Ziel des Epics: Für jede Liga ist ohne Codelesen erkennbar, **warum** der Trader (nicht) handelt. Ändert kein Handelsverhalten.

### E01.00 – Debug-Liquidation = verwendete Liquidation
- **Priorität:** P1 · **Status:** done · **Abhängig von:** E00 · **Aufwand:** S · **Flag:** –
- **Ergebnis:** `sync/trader.py` berechnet die Liquidation nur noch einmal. Das Debug-Feld `liquidation` enthält jetzt den Wert, der den Kredit begrenzt hat; neu ist `liquidation_full_day` zum Vergleich.
  - Tests in `smoke_manager_tools.py`: Kredit = `credit(…, liquidation)`; bei ausgeschöpftem Tageslimit ist die Liquidation 0, während `liquidation_full_day` > 0 ist. Der Test schlägt ohne die Korrektur fehl.
  - Volle Backend-Suite grün (15/15, lokal). Frontend nicht ausgeführt; es zeigt dasselbe Feld weiter an.
  - Abnahme 1–3 erfüllt.
- **Ausgangssituation:** Debug-Feld `liquidation` rechnet mit `opts.daily_sales` und `own0`, der Kredit mit `sales_left` und `own` nach Ausstiegsverkauf (`sync/trader.py:792` vs. `:979`, KI-04).
- **Ziel:** Das Protokoll zeigt den Wert, der den Kredit tatsächlich begrenzt hat.
- **Umfang:** Liquidation einmal berechnen, in Variable halten, beides loggen: `liquidation` (verwendet) und `liquidation_full_day` (zum Vergleich).
- **Nicht enthalten:** Änderung der Kreditlogik.
- **Module:** `sync/trader.py`, Test in `tests/check_trader_safety.py`.
- **Sicherheit:** keine Verhaltensänderung (S2 unberührt). Test: Aktionen vor/nach identisch.
- **Abnahmekriterien:** 1. `debug["liquidation"]` = Argument der Kreditberechnung. 2. Nach einem heutigen Verkauf unterscheiden sich `liquidation` und `liquidation_full_day` nachvollziehbar. 3. Bestehende Tests grün.
- **Pflichttests:** Planung mit 2 heutigen Verkäufen bei `daily_sales=3`: `liquidation` umfasst höchstens 1 Spieler.
- **Migration:** keine · **Rollback:** Revert des Commits.

### E01.01 – Reale JSON-Exporte analysieren
- **Priorität:** P1 · **Status:** **done** (27.11.2026, 2 Exporte) · **Abhängig von:** E00.08 · **Aufwand:** S
- **Ergebnis:** `KNOWN_ISSUES.md` Abschnitt B. Hauptursachen: Verkaufsquote 0,9 macht Gewinnhandel unmöglich (KI-26), Qualitätsvergleich über Positionen blockiert Upgrades (KI-27), Reserve > Kontostand. Kredit ist **nicht** die primäre Ursache. Abnahme 1–3 erfüllt; Prioritäten in ADR-011 angepasst. `analyze_export.py` um die Prüfung „Gewinnhandel möglich?“ erweitert. Wiederholung nach E01.02/E01.04 mit frischem Export empfohlen.
- **Ziel:** Ursache(n) der fehlenden Kaufvorschläge mit Daten belegen.
- **Umfang:** `analyze_export.py` je Export; Gegenprüfung der Hypothesen in `KNOWN_ISSUES.md` B; Ergebnis als Abschnitt in `KNOWN_ISSUES.md` (ohne Nutzer-/Liga-IDs, ohne Spielernamen).
- **Abnahmekriterien:** 1. Für die Liga ohne Käufe ist der/die dominierende Ablehnungsgrund/-gründe mit Häufigkeit belegt. 2. Jede Hypothese ist als bestätigt / widerlegt / nicht entscheidbar markiert. 3. Daraus abgeleitete Paketprioritäten sind in `MASTERPLAN.md` angepasst und begründet.
- **Sicherheit:** S16 – Exporte nicht committen, Ergebnisse anonymisiert.
- **Rollback:** entfällt (Analyse).

### E01.02 – Einheitliche Ablehnungscodes
- **Priorität:** P1 · **Status:** ready · **Abhängig von:** E00 · **Aufwand:** M · **Flag:** – (reine Zusatzinformation)
- **Ausgangssituation:** Freitext-Gründe, teils kombiniert (KI-14).
- **Ziel:** Jede Kandidatenentscheidung trägt genau einen primären maschinenlesbaren Code plus optional sekundäre Codes.
- **Umfang:** `core/reasons.py` mit Konstanten (z. B. `NOT_FIT`, `NO_RISING_FORECAST`, `PROFIT_TRADING_OFF`, `STOP_LOSS`, `FORECAST_PAUSE`, `PHASE_FINAL`, `AUCTION_END_UNKNOWN`, `DAILY_BIDS`, `SLOT_TAKEN`, `ELEVEN_GAPS_FIRST`, `COVER_DONE`, `SQUAD_FULL`, `BUDGET_CASH`, `BUDGET_CREDIT_MODE`, `MARGIN_BELOW_MIN`, `ROI_BELOW_MIN`, `PROFIT_ROOM_EXHAUSTED`, `PRICE_PER_POINT`, `NO_UPGRADE`, `PLAY_RATE_LOW`, `PLAY_RATE_UNKNOWN`, `QUALITY_EDGE`, `LOOKAHEAD_WORSE`, `CLUB_LIMIT`, `REBUY_BLOCK`, `UNCONFIRMED_ACTION`, `ROOM_SALE_*`) und deutschem Text je Code. `_price` liefert neben dem Gebot den bindenden Grenzwert (welcher Cap griff), damit „Marge oder Budget“ getrennt wird. `lineup_upgrade` liefert den Ablehnungsgrund. Debug je Marktspieler: `reason`, `reasons_secondary`, `decision` (Text bleibt).
- **Nicht enthalten:** UI (E01.05), Aggregation (E01.03).
- **Module:** `core/reasons.py` (neu), `core/trader.py` (`lineup_upgrade` → Grund), `sync/trader.py` (`_price`, `why`), Tests.
- **Sicherheit:** Entscheidungen unverändert; Test vergleicht Aktionen vor/nach auf den bestehenden Szenarien.
- **Abnahmekriterien:** 1. Kein kombinierter Code; für Gewinnhandel ist unterscheidbar, ob Bargeld, Kreditmodus, `profit_room`, Marge oder Rendite gebunden hat. 2. Jeder Marktspieler im Debug hat einen Code (`NOT_CHECKED` nur, wenn wirklich nicht geprüft). 3. Codes sind dokumentiert (Tabelle in `AUTOTRADER.md` oder `core/reasons.py` als Quelle). 4. `analyze_export.py` nutzt native Codes, Textzuordnung bleibt als Rückfall für alte Exporte.
- **Pflichttests:** je Code mindestens ein Szenario in `check_trader_intelligence.py` oder neuer `check_trader_reasons.py` (in CI aufnehmen).
- **Migration:** keine (JSON im Debug) · **Rollback:** Revert.

### E01.03 – Statistik abgelehnter Kandidaten
- **Priorität:** P2 · **Status:** todo · **Abhängig von:** E01.02 · **Aufwand:** S
- **Ziel:** Je Liga über 1/7/21 Tage: geprüfte Spieler, geeignete, abgelehnte, Top-Gründe (primär/sekundär), je Spieler einmal je Tag gezählt.
- **Umfang:** Aggregation aus `traderdebug` in `sync/trader.py::_stats` oder eigener Funktion; API-Feld im Dashboard. Keine neue Tabelle (21 Tage Debug reichen; Langzeit in E03.08).
- **Abnahmekriterien:** 1. Zählung dedupliziert je (Spieler, Tag, Code). 2. Laufzeit < 200 ms bei 21 Tagen Demo-Daten. 3. Liga-/Nutzer-Isolation getestet.
- **Pflichttests:** Isolation, Deduplizierung, leere Historie.
- **Rollback:** Feld entfernen.

### E01.04 – Maximalgebot und internes Budget vergleichen
- **Priorität:** P1 · **Status:** done (Backend; Anzeige im UI folgt mit E01.05) · **Abhängig von:** E01.00 · **Aufwand:** S
- **Ergebnis:** Reine Funktion `core/trader.py::money_check` mit stabilen Codes `RESERVE`, `DEBT`, `LIQUIDATION`, `CREDIT_MODE`, `PHASE`, `PROFIT_ROOM`. Jede Planungsrunde schreibt `money_check` ins Debug-Protokoll und ins `/dashboard`: `max_bid`, `max_bid_free`, `released` und `gap` je Zweck (Startelf/Ersatz/Gewinn), `limits` je Zweck.
  - Der Kredit gilt für eine Auktion, die vor der Deadline endet (konservativ). Pro Gebot zurückgehaltenes Geld für Lücken und Ersatz steht nicht darin; das bleibt eine Entscheidung je Gebot.
  - Tests: 510 neue Checks in `check_trader_safety.py`. Darunter der Fall der Liga ohne Käufe (`CREDIT_MODE` begrenzt den Gewinnhandel), die Phase `final`, Schulden, offene Gebote über dem Kontostand, `profit_room` sowie 500 Zufallsfälle für die Summenidentität. Dazu prüft `smoke_manager_tools.py`, dass das Feld in jeder Planungsrunde vorhanden ist und die Summen stimmen.
  - Aktionen unverändert: Die Funktion wird nur zusätzlich aufgerufen.
  - `analyze_export.py` nutzt das Feld, wenn es vorhanden ist.
  - Volle Suite 15/15 grün. Frontend nicht ausgeführt.
- **Ziel:** Jede Runde protokolliert `max_bid` (Kickbase-Regel), `max_bid_free` (nach offenen Geboten), freigegebenes Budget je Zweck (Startelf/Ersatz/Gewinn, nach Phase und `credit_mode`), Differenz und **welche Grenze** sie verursacht (Reserve, Liquidation, Kreditmodus, Phase, Lücken-/Ersatzreserve, `profit_room`).
- **Module:** `sync/trader.py` (Debug + Dashboard), `core/analytics.py` (nur Aufruf).
- **Abnahmekriterien:** 1. Felder in Debug und `/dashboard`. 2. Summe der ausgewiesenen Abzüge = Differenz (Test). 3. Kein Einfluss auf Aktionen.
- **Pflichttests:** Kontostand 0 + `credit_mode` 1 → Gewinn-Budget 0 mit Grund `BUDGET_CREDIT_MODE`; negativer Kontostand; offene Gebote > Kontostand.
- **Rollback:** Revert.

### E01.05 – Diagnoseansicht im Frontend
- **Priorität:** P2 · **Status:** todo · **Abhängig von:** E01.03, E01.04 · **Aufwand:** M
- **Ziel:** Karte „Warum kauft der Trader nicht?“ auf der Automatik-Seite: Budgetvergleich (Balken Maximalgebot → freigegeben, Abzüge benannt), Top-Gründe, Phase, aktive Pausen, Kaderplätze, Vereinslimits.
- **Module:** `frontend/src/pages/Automation.tsx` (ggf. Teilkomponente auslagern), `api/types.ts`, `api/hooks.ts`.
- **Abnahmekriterien:** 1. 375 px ohne horizontales Scrollen (ui-audit). 2. Leerer Zustand (keine Runde) verständlich. 3. Gründe in Klartext, Code als Tooltip/Detail.
- **Pflichttests:** `npm run build`, ui-audit-Screenshots Desktop + Mobil.

### E01.06 – Was-wäre-wenn-Analyse
- **Priorität:** P2 · **Status:** todo · **Abhängig von:** E01.02, E02.02 (Validierung der geänderten Werte) · **Aufwand:** M
- **Ziel:** `POST /api/automation/trader/whatif` plant die **letzte gespeicherte Runde** mit geänderten Optionen neu und zeigt die Differenz (zusätzliche/entfallene Aktionen, geänderte Gründe), ohne etwas zu speichern oder zu senden.
- **Umfang:** `_plan` mit gespeicherten Eingaben (Kader, Markt, Budget aus dem Debug) als reine Simulation; keine Kickbase-Aufrufe (S12); kein Debug-Log, keine Schatten, kein Push.
- **Abnahmekriterien:** 1. Gleiche Optionen → gleiche Aktionen wie protokolliert (Determinismus-Test). 2. Aufrufzähler des Mock-Clients = 0. 3. Keine DB-Schreibvorgänge (Test über Zeilenzahlen).
- **Offenes Risiko:** Der Debug enthält nicht alle Eingaben (z. B. Historien); ggf. E03.01-Snapshot als Grundlage → dann Abhängigkeit E03.01.
