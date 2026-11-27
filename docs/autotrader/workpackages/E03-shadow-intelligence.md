# E03 – Shadow Intelligence Engine 2.0

Ziel des Epics: Der Trader lernt auch ohne eigene Transfers – aus jeder relevanten Ablehnung, mit sauberer Trennung von echt/hypothetisch und ohne Zukunftswissen. ADR-006/007. Flag: `decision_snapshots`.

### E03.01 – Entscheidungs-Snapshots speichern
- **Priorität:** P1 · **Status:** todo · **Abhängig von:** E01.02, E02.04 · **Aufwand:** M · **Flag:** `decision_snapshots` (`off` = keine Zeilen)
- **Ziel:** Tabelle `decisionsnapshot`: eindeutig je (`user_id`, `league_id`, `player_id`, `listed_at`); Inhalt: Zeitpunkt, Marktwert, Preis/Gebotsspanne, Auktionsende, Prognose (roh + skaliert), erwartete Punkte, Einsatzdaten, Kontostand, offene Gebote (Summe), freigegebenes Budget je Zweck, Kaderzustand (Größe, Lücken, Ersatzlücken), Reason Codes, `config_version`, `model_version`, hypothetisches Gebot(e).
- **Umfang:** Schreiben aus bereits geladenen Rundendaten; Upsert (erste Entscheidung bleibt, letzte wird zusätzlich vermerkt: `first_seen`, `last_seen`, `last_reason`).
- **Sicherheit:** S11, S12 – Test mit zählendem Mock-Client (0 zusätzliche Aufrufe).
- **Abnahmekriterien:** 1. Eine Zeile je Auktion und Nutzer, auch bei 100 Runden. 2. Keine Zeile bei Flag `off`. 3. Laufzeit +≤ 10 % je Runde (benchmark_audit). 4. Index auf (`league_id`, `listed_at`) und (`user_id`, `league_id`, `resolved`).
- **Migration:** neue Tabelle (additiv). · **Rollback:** Flag `off`; Tabelle bleibt ungenutzt.

### E03.02 – Abgelehnte Kandidaten aller Zwecke erfassen
- **Priorität:** P1 · **Abhängig von:** E03.01 · **Aufwand:** S
- **Ziel:** Snapshots auch für Startelf-, Ersatz-, Budget-, Kader-, Vereinslimit-, Phase-, Stop-Loss-Ablehnungen und verlorene Auktionen (heute nur Gewinnhandel, KI-09).
- **Abnahmekriterien:** Jede Kategorie aus der Übergabe §8.1 ist einem Reason Code zugeordnet und im Test vertreten.

### E03.03 – Systematische Stichprobenauswahl
- **Priorität:** P2 · **Abhängig von:** E03.02 · **Aufwand:** S
- **Ziel:** Begrenzte Zahl je Runde (konfigurierbar), stratifiziert nach Preisklasse × Ablehnungsgrund (erweitert die bestehende Preisklassen-Streuung), Vorrang für bisher unterrepräsentierte Schichten.
- **Abnahmekriterien:** Bei 200 Kandidaten höchstens N neue Snapshots je Runde; jede vorhandene Schicht erscheint innerhalb von k Runden.

### E03.04 – Alternative Gebote simulieren
- **Priorität:** P2 · **Abhängig von:** E03.01 · **Aufwand:** M
- **Ziel:** Je Snapshot Varianten: Mindestgebot, defensiv, Standard, aggressiv, EV-optimal. Abrechnung mit bekanntem Transfer: gewonnen nur bei Gebot > Gewinnerpreis; Gleichstand = unbekannt; verschwunden ohne Transfer = unbekannt (kein Lernen); kein Käufer (Kickbase-Spieler ohne Gebot) gesondert.
- **Abnahmekriterien:** 1. Varianten zählen als **eine** Stichprobe (ADR-007). 2. Unbekannte Gewinnerpreise werden nie geschätzt. 3. Simulationsgrenze ausgewiesen: „andere Manager hätten anders reagieren können“.

### E03.05 – Alternative Verkaufsstrategien simulieren
- **Priorität:** P2 · **Abhängig von:** E03.04 · **Aufwand:** M
- **Ziel:** Für hypothetisch gewonnene und echte Positionen: Verkauf nach 1/2/3 Updates, Prognose-Ausstieg, Trailing-Stop, Deadline-Verkauf – jeweils **vorab definierte Regel**, Bewertung zum jeweiligen Tageswert × Quote.
- **Abnahmekriterien:** 1. Höchstwert nur als Feld `diagnostic_peak`, nie als Ergebnis einer Strategie. 2. Kein Zukunftswissen: Regel entscheidet je Tag nur mit Werten bis zu diesem Tag (Test: geänderte Zukunft ändert Entscheidung nicht).

### E03.06 – Entgangene Gewinne und vermiedene Verluste
- **Priorität:** P2 · **Abhängig von:** E03.05 · **Aufwand:** S
- **Ziel:** Ergebnisarten getrennt: realisiert, hypothetisch einzeln, vermiedener Verlust, unbekannter Ausgang, nicht finanzierbar, hypothetisch finanzierbar. Je Reason Code: Summe, Anzahl, Median.
- **Abnahmekriterien:** Keine Summe einzelner Hypothesen wird als erreichbarer Gesamtgewinn bezeichnet (gemeinsam realisierbar erst mit E09).

### E03.07 – Lerngewichtung und Deduplizierung
- **Priorität:** P2 · **Abhängig von:** E03.06 · **Aufwand:** S
- **Ziel:** Gewicht nach Alter, Echtheit (echt 1,0, Schatten ≤ 0,5), Stichprobe; je Auktion höchstens einmal in Lernverfahren.

### E03.08 – Aufbewahrung und Performance
- **Priorität:** P2 · **Abhängig von:** E03.01 · **Aufwand:** S
- **Ziel:** Konfigurierbare Aufbewahrung (Standard 120 Tage wie heute), danach Verdichtung in Tagesaggregate je Liga × Code × Preisklasse; Löschlauf in Batches.
- **Abnahmekriterien:** DB-Wachstum bei 6 Ligen × 1 Jahr geschätzt und dokumentiert; Löschlauf < 1 s auf 100.000 Zeilen (SQLite).

### E03.09 – Shadow-Dashboard
- **Priorität:** P3 · **Abhängig von:** E03.06 · **Aufwand:** M
- **Ziel:** Beobachtete Auktionen, verpasste Chancen, vermiedene Verluste, Gründe, alternative Gebote/Haltedauern, mit deutlicher Kennzeichnung „hypothetisch“.
