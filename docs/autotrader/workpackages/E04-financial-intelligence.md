# E04 – Financial Intelligence

Ziel des Epics: Kapital bis zum tatsächlich verfügbaren Maximalgebot nutzen können, wenn ein konservativer Finanzierungsplan bis zur Deadline existiert. ADR-005. Alle Pakete hinter Flags; bei `off` gilt die 2.0-Formel (`credit`, `liquidation_value`) unverändert.

Grundbaustein `core/finance.py` (rein, ohne DB und Client):
```
LiquidityPlan(budget, open_bids, squad, deadline, now, sales_used_today, config)
  -> capacity per day, collateral register {player_id: plan_id}, scenarios {optimistic, realistic, pessimistic},
     released credit per purpose, repayment schedule, reasons
```

### E04.01 – Maximalgebot und interne Kreditfreigabe trennen
- **Priorität:** P1 · **Status:** todo · **Abhängig von:** E01.04, E02.08 · **Aufwand:** S · **Flag:** –
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
- **Priorität:** P1 · **Abhängig von:** E04.01, **E10.00** (Stressparameter); E04.02 nicht mehr nötig · **Aufwand:** M
- **Startwerte aus den Exporten (§9.2):** pessimistisch steigende Prognose − 2 % je Update, fallende − 4 % je Update, Quote 100 % (Kickbase). Ab ≥ 14 Tagen ersetzt durch p5 bzw. p1 aus E10.00.
- **Ziel:** Erlös je Spieler und Tag in drei Szenarien: optimistisch (Prognose), realistisch (Prognose × Vertrauen, Quote erwartet), pessimistisch (Abschlag `stress_value_drop_pct` je Update, Quote pessimistisch). Freigabe nur auf pessimistisch.
- **Abnahmekriterien:** 1. Fehlende Prognose → pessimistisch = Abschlag ohne Gegenwert. 2. Sinkende Marktwerte und schlechtere Erlöse reduzieren die Freigabe monoton (Eigenschaftstest).

### E04.04 – Gewinnspieler als bedingte Tilgung
- **Priorität:** P1 · **Abhängig von:** E04.03, E03.01 (Messung im Schatten vor Live) · **Aufwand:** M · **Flag:** `conditional_repayment`
- **Testfall aus den Daten:** Liga B (11 Spieler, Liquidation 0, Kreditrahmen 54 Mio.). Dort ist das der einzige Kredithebel.
- **Ziel:** Ein Gewinn-Gebot darf Kredit nutzen, wenn der pessimistische Plan **mit** dem Zuschlag (Verkauf des Ziels frühestens nach `min_hold_hours`, vor der Deadline, zum pessimistischen Erlös) und **ohne** Zuschlag (Gebot kostet nichts) aufgeht.
- **Sicherheit:** S3, S4 – der Neuzugang ist Sicherheit nur für sein eigenes Gebot; nie Ersatz/Starter; nie für andere Pläne.
- **Abnahmekriterien:** Beispiel der Übergabe §6.2 (0 € Kontostand, 33 Mio. Max, 30 Mio. Käufe, 31,8 Mio. Erlös) wird bei ausreichender Zeit und Prognosequalität freigegeben, bei Deadline < `min_hold_hours` + Puffer abgelehnt (`FINANCE_REPAY_TOO_LATE`); mehrere gleichzeitig gewonnene Auktionen bleiben gemeinsam gedeckt.

### E04.05 – Finanzierung von Startelf-Upgrades
- **Priorität:** P1 · **Abhängig von:** E04.03 · **Aufwand:** M · **Flag:** `upgrade_financing`
- **Testfall aus den Daten:** Liga A. Nach E05.08 gibt es 8 Upgrade-Kandidaten; finanziert werden können sie nur über den verdrängten Starter oder die freigegebene Bank (E05.02).
- **Ziel:** Bedingter Plan „Kauf X → nach bestätigtem Zuschlag Verkauf des Verdrängten Y“; Y ist bis zur Bestätigung geschützt, danach Sicherheit nur für diesen Plan.
- **Umfang:** Abhängigkeit als Datensatz im TradeLog (`details.depends_on`), Ausführung des Verkaufs erst in einer Runde nach `won`.
- **Abnahmekriterien:** Beispiel §6.3 (19 Mio. Kauf, 13,5 + 6 Mio.); verlorene Auktion → Y bleibt; Neustart zwischen Zuschlag und Verkauf → Plan wird aus TradeLog rekonstruiert.

### E04.06 – Gemeinsame Finanzierung offener Gebote
- **Priorität:** P1 · **Abhängig von:** E04.04, E04.05 · **Aufwand:** M
- **Ziel:** Sicherheiten-Register über alle offenen und geplanten Gebote (manuelle eingeschlossen: belasten, sichern nichts); kein Erlös doppelt.
- **Abnahmekriterien:** Doppelt beanspruchter Erlös → zweites Gebot `FINANCE_COLLATERAL_TAKEN`; Eigenschaftstest: Σ Sicherheiten ≤ Σ Einzelerlöse.

### E04.07 – Dynamische Kreditauslastung
- **Priorität:** P2 · **Abhängig von:** E04.06, E02.04 · **Aufwand:** S
- **Ziel:** `max_utilization_pct` plus Abhängigkeit von Zeit bis Deadline, verbleibenden Updates, Prognosegüte (über Regelwerk E08.01 oder feste Kurve im Schema).

### E04.08 – Deadline-Liquiditätsprognose
- **Priorität:** P2 · **Abhängig von:** E04.06 · **Aufwand:** S
- **Ziel:** Erwarteter und pessimistischer Kontostand zum Anpfiff je Runde in Debug/Dashboard; Push, wenn pessimistisch < 0 vor Beginn der Tilgungsphase.

### E04.09 – Automatische Tilgungsstrategie
- **Priorität:** P2 · **Abhängig von:** E04.08 · **Aufwand:** M
- **Ziel:** Laufender Tilgungsplan (welcher Verkauf an welchem Tag), Verkäufe vor der `repay`-Phase, wenn die Kapazität späterer Tage nicht reicht; Neuplanung bei Abweichung. Rettungsverkäufe 2.0 bleiben letzte Linie.
- **Abnahmekriterien:** Ausfall der API für den letzten Tag → Plan hat Schulden bereits am Vortag getilgt (Puffer).

### E04.10 – Risk-Engine-Integration
- **Priorität:** P1 · **Abhängig von:** E04.06 · **Aufwand:** S
- **Ziel:** Risk Engine prüft unabhängig: jedes Gebot, das Kredit nutzt, verweist auf einen Plan mit pessimistischem Deadline-Saldo ≥ Reserve; Register ohne Doppelanrechnung. Neue Codes `FINANCE_PLAN_MISSING`, `FINANCE_PESSIMISTIC_NEGATIVE`, `FINANCE_COLLATERAL_TAKEN`.

### E04.11 – Finanzierungsübersicht (UI)
- **Priorität:** P3 · **Abhängig von:** E04.08 · **Aufwand:** M
- **Ziel:** Financial Dashboard: Maximalgebot, internes Budget, Auslastung, Liquiditätsprognose, Tilgungsplan, Risiken.
