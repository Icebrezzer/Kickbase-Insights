# E04 – Financial Intelligence

Ziel des Epics: Kapital bis zum tatsächlich verfügbaren Maximalgebot nutzen können, wenn ein konservativer Finanzierungsplan bis zur Deadline existiert. ADR-005. Alle Pakete hinter Flags; bei `off` gilt die 2.0-Formel (`credit`, `liquidation_value`) unverändert.

Grundbaustein `core/finance.py` (rein, ohne DB und Client):
```
LiquidityPlan(budget, open_bids, squad, deadline, now, sales_used_today, config)
  -> capacity per day, collateral register {player_id: plan_id}, scenarios {optimistic, realistic, pessimistic},
     released credit per purpose, repayment schedule, reasons
```

### E04.01 – Maximalgebot und interne Kreditfreigabe trennen
- **Priorität:** P1 · **Status:** done
- **Ergebnis:** `core/finance.py` mit reinen Funktionen. Das Szenario `current` ist exakt die Liquidation von 2.0: 300 Zufallskader in allen Bank-Modi, `finance.liquidation(..., "current") == t.liquidation_value(...)`. Das Maximalgebot steht seit E01.04 getrennt (`money_check`). Die Planung nutzt die alte Kreditformel weiter, solange `scenario_credit` aus ist. · **Abhängig von:** E01.04, E02.08 · **Aufwand:** S · **Flag:** –
- **Ziel:** `core/finance.py` mit Datentypen; `credit()` wird dort als `release_v2` (identisch zu heute) abgebildet; Planung nutzt den neuen Aufruf, Ergebnis bit-identisch.
- **Abnahmekriterien:** Alle Safety-Checks grün; Vergleichstest alt = neu auf 1.000 Zufallsfällen (fester Seed).

### E04.02 – Mehrtägige Liquidationskapazität
- **Priorität:** **P2 (zurückgestuft, MASTERPLAN §9.2:** bringt in beiden realen Ligen 0 €, weil der Kaderschutz bindet und nicht die Verkaufslimits) · **Abhängig von:** E04.01, E05.02 · **Aufwand:** M · **Flag:** `multi_day_liquidation`
- **Ziel:** Kapazität bis zur Deadline: je verbleibendem Berlin-Tag `daily_sales` (heute: `sales_left`), Sperrenablauf (`MIN_HOLD`, Startelf-Sperre), Puffer `api_outage_buffer_hours`, nach jedem simulierten Verkauf Kaderprüfung (Ersatz, keine Lücke).
- **Nicht enthalten:** Marktwertentwicklung (E04.03).
- **Sicherheit:** S2 (jeder Spieler einmal), S10. Unbekannte Deadline → nur heutige Kapazität (wie 2.0).
- **Abnahmekriterien:** 1. Szenarien der Übergabe §25: Deadline in 6 Tagen, in 24 h, < 1 h, unbekannt, verbrauchte Verkäufe, gesperrte Spieler. 2. Ein Spieler mit Sperre bis nach der Deadline zählt nicht. 3. Flag `off` → identisch 2.0; `shadow` → nur Debug-Feld `liquidation_multi_day`.
- **Pflichttests:** neue `check_trader_finance.py` (in CI).

### E04.03 – Szenariobasierte Verkaufserlöse
- **Status:** done · **Flag:** `scenario_credit` (neu)
- **Ergebnis:**
  - `finance.sale_value` bewertet einen Verkauf in den Szenarien `optimistic`, `realistic` (Prognose × gelerntes Vertrauen) und `pessimistic`. Pessimistisch heißt: Prognose minus 2 % je Update bei steigender, minus 4 % bei fallender oder fehlender Prognose, dazu ein Update Puffer.
  - Jede Runde schreibt die Liquidation in allen Szenarien ins Debug-Protokoll (`finance.scenarios`). Mit dem Flag bestimmt die pessimistische Liquidation den Kredit; der Wert ist nie höher als in 2.0 (Test).
  - Nachrechnung Liga A, letzte Runde: aktuell 14,4 Mio., pessimistisch 14,1 Mio. (volle Bank); 34,5 bzw. 33,8 Mio. ohne Bank.
  - Die Stresswerte sind feste Startwerte in `core/finance.py` (ADR-013) und werden mit E10.00 nach ≥ 14 Tagen kalibriert.
- **Priorität:** P1 · **Abhängig von:** E04.01, **E10.00** (Stressparameter); E04.02 nicht mehr nötig · **Aufwand:** M
- **Startwerte aus den Exporten (§9.2):** pessimistisch steigende Prognose − 2 % je Update, fallende − 4 % je Update, Quote 100 % (Kickbase). Ab ≥ 14 Tagen ersetzt durch p5 bzw. p1 aus E10.00.
- **Ziel:** Erlös je Spieler und Tag in drei Szenarien: optimistisch (Prognose), realistisch (Prognose × Vertrauen, Quote erwartet), pessimistisch (Abschlag `stress_value_drop_pct` je Update, Quote pessimistisch). Freigabe nur auf pessimistisch.
- **Abnahmekriterien:** 1. Fehlende Prognose → pessimistisch = Abschlag ohne Gegenwert. 2. Sinkende Marktwerte und schlechtere Erlöse reduzieren die Freigabe monoton (Eigenschaftstest).

### E04.04 – Gewinnspieler als bedingte Tilgung
- **Status:** done
- **Ergebnis:**
  - `finance.self_collateral`: Ein Gewinnziel sichert sein eigenes Gebot mit seinem pessimistischen Erlös am Beginn der Tilgungsphase. Bedingung: Auktionsende + 20 h Haltesperre + 6 h Puffer liegen vor dem Beginn der Tilgungsphase, das Ziel ist fit und hat eine steigende Prognose.
  - Mit dem Flag zählt die Sicherheit zum Gebotsbudget. Der Kreditmodus begrenzt nur den Grundkredit, nicht die bedingte Sicherheit (ADR-013).
  - Nachrechnung: In Liga A sichern sich vier Gewinnkandidaten mit 82–83 % ihres Preises selbst ab, in Liga B drei (z. B. 26,0 von 30,9 Mio.). Den Rest muss echter Kredit decken.
  - Übergabe §6.2 als Test: Bei Kontostand 0 und drei Spielern zu je 10 Mio. mit +5 % Prognose bringt jeder pessimistisch 8,6 Mio. Ohne Kredit wird keines der drei Gebote freigegeben, mit 4,2 Mio. Kredit alle drei, mit 10.000 € weniger nur zwei.
- **Priorität:** P1 · **Abhängig von:** E04.03, E03.01 (Messung im Schatten vor Live) · **Aufwand:** M · **Flag:** `conditional_repayment`
- **Testfall aus den Daten:** Liga B (11 Spieler, Liquidation 0, Kreditrahmen 54 Mio.). Dort ist das der einzige Kredithebel.
- **Ziel:** Ein Gewinn-Gebot darf Kredit nutzen, wenn der pessimistische Plan **mit** dem Zuschlag (Verkauf des Ziels frühestens nach `min_hold_hours`, vor der Deadline, zum pessimistischen Erlös) und **ohne** Zuschlag (Gebot kostet nichts) aufgeht.
- **Sicherheit:** S3, S4 – der Neuzugang ist Sicherheit nur für sein eigenes Gebot; nie Ersatz/Starter; nie für andere Pläne.
- **Abnahmekriterien:** Beispiel der Übergabe §6.2 (0 € Kontostand, 33 Mio. Max, 30 Mio. Käufe, 31,8 Mio. Erlös) wird bei ausreichender Zeit und Prognosequalität freigegeben, bei Deadline < `min_hold_hours` + Puffer abgelehnt (`FINANCE_REPAY_TOO_LATE`); mehrere gleichzeitig gewonnene Auktionen bleiben gemeinsam gedeckt.

### E04.05 – Finanzierung von Startelf-Upgrades
- **Status:** done
- **Ergebnis:**
  - `finance.replaced_collateral`: Der verdrängte Starter sichert ein Startelf-Gebot. Bedingungen:
    - nicht gesperrt;
    - sein Verkauf hält mit dem Neuzugang den Ersatzschutz der aktuellen Bank-Strategie ein und reißt keine Lücke;
    - die Auktion endet mindestens 6 h vor dem Beginn der Tilgungsphase.
  - Bis zum Zuschlag bleibt er Starter und geschützt. Nach dem Zuschlag ist er Bankspieler, und die normale Liquidation bzw. Rettung verkauft ihn, falls nötig. Geht die Auktion verloren, entsteht kein Kredit.
  - Die Abhängigkeit „erst verkaufen, wenn der Zuschlag da ist“ ergibt sich so aus den bestehenden Regeln, ohne zusätzlichen Zustand.
  - Befund Liga A: Ohne **automatische Aufstellung** sind alle Starter dauerhaft gesperrt (2.0-Regel), deshalb greift die Upgrade-Finanzierung dort nicht. Sie braucht „Beste Elf automatisch aufstellen“.
- **Priorität:** P1 · **Abhängig von:** E04.03 · **Aufwand:** M · **Flag:** `upgrade_financing`
- **Testfall aus den Daten:** Liga A. Nach E05.08 gibt es 8 Upgrade-Kandidaten; finanziert werden können sie nur über den verdrängten Starter oder die freigegebene Bank (E05.02).
- **Ziel:** Bedingter Plan „Kauf X → nach bestätigtem Zuschlag Verkauf des Verdrängten Y“; Y ist bis zur Bestätigung geschützt, danach Sicherheit nur für diesen Plan.
- **Umfang:** Abhängigkeit als Datensatz im TradeLog (`details.depends_on`), Ausführung des Verkaufs erst in einer Runde nach `won`.
- **Abnahmekriterien:** Beispiel §6.3 (19 Mio. Kauf, 13,5 + 6 Mio.); verlorene Auktion → Y bleibt; Neustart zwischen Zuschlag und Verkauf → Plan wird aus TradeLog rekonstruiert.

### E04.06 – Gemeinsame Finanzierung offener Gebote
- **Status:** done
- **Ergebnis:**
  - Register je Runde: Jeder Spieler sichert höchstens ein Gebot. Gebote früherer Runden schreiben ihre Sicherheiten ins Handelsprotokoll (`details.collateral`), spätere Runden lesen sie als belegt (`claimed_before`).
  - Der Grundkredit bleibt ein gemeinsamer Topf für alle Gebote (laufende Summe in der Risk Engine). Bedingte Sicherheiten kommen je Gebot dazu.
  - Manuelle Gebote belasten den Worst Case wie bisher und sichern nichts.
- **Priorität:** P1 · **Abhängig von:** E04.04, E04.05 · **Aufwand:** M
- **Ziel:** Sicherheiten-Register über alle offenen und geplanten Gebote (manuelle eingeschlossen: belasten, sichern nichts); kein Erlös doppelt.
- **Abnahmekriterien:** Doppelt beanspruchter Erlös → zweites Gebot `FINANCE_COLLATERAL_TAKEN`; Eigenschaftstest: Σ Sicherheiten ≤ Σ Einzelerlöse.

### E04.07 – Dynamische Kreditauslastung
- **Priorität:** P2 · **Abhängig von:** E04.06, E02.04 · **Aufwand:** S
- **Ziel:** `max_utilization_pct` plus Abhängigkeit von Zeit bis Deadline, verbleibenden Updates, Prognosegüte (über Regelwerk E08.01 oder feste Kurve im Schema).

### E04.08 – Deadline-Liquiditätsprognose
- **Priorität:** P2 · **Status:** done · **Abhängig von:** E04.06 · **Aufwand:** S
- **Ergebnis:**
  - `finance.deadline_forecast` berechnet je Planungsrunde den Kontostand zum Anpfiff: Worst Case (alle Gebote mit Ende vor der Deadline gewinnen), erwartet (jedes Gebot mit seiner Zuschlagschance, unbekannt = gewonnen) und pessimistisch nach allen Verkäufen bis zur Tilgungsphase.
  - Für die Verkäufe zählen die heute übrigen plus das Tageslimit jedes weiteren Tages (`sales_until`), pessimistisch bewertet, mit der Ersatzbank der Tilgungsphase.
  - Status `ok`, `needs_sales` oder `short` steht im Debug-Protokoll und im Dashboard-API (`deadline_forecast`).
  - Bei `short` vor der Tilgungsphase kommt einmal je Spieltag die Push-Warnung „Spieltag gefährdet“.
  - Nur Diagnose, kein Flag nötig; Entscheidungen unverändert.
  - Tests: 7 Checks in `check_trader_finance.py`, 2 Smoke-Prüfungen.
- **Ziel:** Erwarteter und pessimistischer Kontostand zum Anpfiff je Runde in Debug/Dashboard; Push, wenn pessimistisch < 0 vor Beginn der Tilgungsphase.

### E04.09 – Automatische Tilgungsstrategie
- **Priorität:** P2 · **Status:** done (Teil 1) · **Abhängig von:** E04.08 · **Aufwand:** M · **Flag:** `early_repayment`
- **Ergebnis (Teil 1):**
  - Mit dem Flag verkauft der Trader ein **bestätigtes** Minus schon ab der Vorbereitungsphase (24 Std. vor dem Spieltag) zurück, statt erst ab dem letzten Update. Ein Serverausfall am Vorabend hinterlässt so kein Minus mehr (bekannte Grenze aus 2.0).
  - Verkauft wird wie in der Rettung: ein Verkauf je Runde, geringster Punktverlust je Euro, gesperrte Spieler geschützt. Offene Gebote zieht er erst in der Tilgungsphase zurück, sie können noch verloren gehen.
  - Ohne Flag bleibt alles wie bisher. Tage vor dem Spieltag passiert auch mit Flag nichts.
  - Tests: Smoke-Prüfungen (Flag aus: kein Verkauf in `prepare`; Flag an: nur Rettungsverkauf; 3 Tage vorher: nichts).
- **Offen (Teil 2):** ein laufender Tilgungsplan, der Verkäufe vor die Vorbereitungsphase legt, wenn die Kapazität späterer Tage laut E04.08 nicht reicht. Er braucht die mehrtägige Liquidation (E04.02).
- **Ziel:** Laufender Tilgungsplan (welcher Verkauf an welchem Tag), Verkäufe vor der `repay`-Phase, wenn die Kapazität späterer Tage nicht reicht; Neuplanung bei Abweichung. Rettungsverkäufe 2.0 bleiben letzte Linie.
- **Abnahmekriterien:** Ausfall der API für den letzten Tag → Plan hat Schulden bereits am Vortag getilgt (Puffer).

### E04.10 – Risk-Engine-Integration
- **Status:** done
- **Ergebnis:**
  - `risk.validate` rechnet jede beanspruchte Sicherheit aus Kader und Listing selbst nach (`finance.check_collateral`) und prüft sie gegen das Register. Neue Codes: `FINANCE_COLLATERAL_TAKEN` (doppelt beansprucht) und `FINANCE_PLAN_INVALID` (hält der Nachrechnung nicht stand, z. B. überhöhter Wert).
  - Der Kill-Switch und alle übrigen Prüfungen gehen weiter vor.
  - Tests: `check_trader_finance.py` (629 Checks, in CI).
- **Priorität:** P1 · **Abhängig von:** E04.06 · **Aufwand:** S
- **Ziel:** Risk Engine prüft unabhängig: jedes Gebot, das Kredit nutzt, verweist auf einen Plan mit pessimistischem Deadline-Saldo ≥ Reserve; Register ohne Doppelanrechnung. Neue Codes `FINANCE_PLAN_MISSING`, `FINANCE_PESSIMISTIC_NEGATIVE`, `FINANCE_COLLATERAL_TAKEN`.

### E04.11 – Finanzierungsübersicht (UI)
- **Priorität:** P3 · **Abhängig von:** E04.08 · **Aufwand:** M
- **Ziel:** Financial Dashboard: Maximalgebot, internes Budget, Auslastung, Liquiditätsprognose, Tilgungsplan, Risiken.
