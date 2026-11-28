# E03 – Shadow Intelligence Engine 2.0

Ziel des Epics: Der Trader lernt auch ohne eigene Transfers – aus jeder relevanten Ablehnung, mit sauberer Trennung von echt/hypothetisch und ohne Zukunftswissen. ADR-006/007. Flag: `decision_snapshots`.

### E03.01 – Entscheidungs-Snapshots speichern
- **Priorität:** P1 · **Status:** done · **Abhängig von:** E01.02, E02.04 · **Aufwand:** M · **Flag:** `decision_snapshots` (`off` = keine Zeilen)
- **Ergebnis:**
  - Neue Tabelle `decisionsnapshot` (additiv, ADR-010). Schlüssel: Nutzer, Liga, Spieler und Auktion. Die Auktion ist der Listungszeitpunkt `dt`, sonst das Auktionsende, sonst der Marktwert-Tag.
  - `TraderService._snapshot` schreibt am Ende jeder Planungsrunde (nicht in Rettungsrunden) beim ersten Sehen einer Auktion:
    - Phase;
    - Marktwert, Preis und Gebotsspanne;
    - Prognose nach 1 und 2 Updates (ungeskaliert) und Gewinn (skaliert);
    - erwartete Punkte, Einsatzquote, Datenmenge und Fitness;
    - Kontostand, offene Gebote, freigegebenes Geld je Zweck (E01.04), Kadergröße und Lücken;
    - den passenden Zweck, Mindestgebot und hypothetisches Gebot (gelernte Höhe), Gewinnchance und Netto beim Mindestgebot;
    - Haupt- und Nebengründe;
    - Konfigurations- und Modellversion, Verkaufsquote und Prognosehorizont.
  - Spätere Runden schreiben nur, wenn sich der Grund ändert (`last_reason`, `last_changed`); die erste Entscheidung bleibt.
  - Aufbewahrung 120 Tage, einmal täglich bereinigt. Ein Fehler beim Speichern bricht keine Runde ab.
  - Es gibt keinen Kickbase-Aufruf: `_plan` hat keinen Client und nutzt nur geladene Daten (S12).
  - Abnahme:
    1. Eine Zeile je Auktion auch nach mehreren Runden.
    2. Keine Zeile bei Flag `off`.
    3. `benchmark_audit` mit Flag: Median 105,5–107,7 ms gegenüber 105,1–105,7 ms ohne Flag (≤ +2,5 %), eine SQL-Abfrage mehr.
    4. Index auf (`league_id`, `first_seen`) und `resolved`.
  - Mit Flag sind die Entscheidungen identisch zu ohne Flag (Smoke).
  - Ein älteres Image startet weiter auf der Datenbank (geprüft).
- **Ziel:** Tabelle `decisionsnapshot`: eindeutig je (`user_id`, `league_id`, `player_id`, `listed_at`); Inhalt: Zeitpunkt, Marktwert, Preis/Gebotsspanne, Auktionsende, Prognose (roh + skaliert), erwartete Punkte, Einsatzdaten, Kontostand, offene Gebote (Summe), freigegebenes Budget je Zweck, Kaderzustand (Größe, Lücken, Ersatzlücken), Reason Codes, `config_version`, `model_version`, hypothetisches Gebot(e).
- **Umfang:** Schreiben aus bereits geladenen Rundendaten; Upsert (erste Entscheidung bleibt, letzte wird zusätzlich vermerkt: `first_seen`, `last_seen`, `last_reason`).
- **Sicherheit:** S11, S12 – Test mit zählendem Mock-Client (0 zusätzliche Aufrufe).
- **Abnahmekriterien:** 1. Eine Zeile je Auktion und Nutzer, auch bei 100 Runden. 2. Keine Zeile bei Flag `off`. 3. Laufzeit +≤ 10 % je Runde (benchmark_audit). 4. Index auf (`league_id`, `listed_at`) und (`user_id`, `league_id`, `resolved`).
- **Migration:** neue Tabelle (additiv). · **Rollback:** Flag `off`; Tabelle bleibt ungenutzt.

### E03.02 – Abgelehnte Kandidaten aller Zwecke erfassen
- **Priorität:** P1 · **Status:** done · **Abhängig von:** E03.01 · **Aufwand:** S
- **Ergebnis:**
  - Snapshots entstehen für jeden Marktkandidaten mit allen Ablehnungscodes aus E01.02. Das deckt Budget, Kreditrahmen (über die Geldgrenzen), Marge, Rendite, Einsatzquote, Kaderplatz, Ersatz, Preis je Punkt, Pausen, Phase und Tageslimit ab.
  - Zusätzlich werden übersprungene Spieler erfasst: Vereinslimit, Rückkaufsperre, unklarer Aufruf und abgelaufene Auktion.
  - Eigene Spieler, eigene Gebote und Spieler ohne Marktdaten sind keine Kaufentscheidung und bleiben außen vor (Test).
  - Noch nicht abgedeckt sind verlorene Auktionen sowie zu frühe oder zu späte Verkäufe. Sie entstehen nicht in der Planung, sondern bei der Abrechnung, und kommen mit E03.04/E03.05.
- **Ziel:** Snapshots auch für Startelf-, Ersatz-, Budget-, Kader-, Vereinslimit-, Phase-, Stop-Loss-Ablehnungen und verlorene Auktionen (heute nur Gewinnhandel, KI-09).
- **Abnahmekriterien:** Jede Kategorie aus der Übergabe §8.1 ist einem Reason Code zugeordnet und im Test vertreten.

### E03.03 – Systematische Stichprobenauswahl
- **Status W6: umgesetzt und geprüft.** Gewichtete Auswahl nach Preisklasse und Hauptgrund aus dem Bestand des Nutzers in der Liga. Limit 1–200, Standard 32. Bestandspflege verbraucht keine Plätze. 200 Kandidaten, 20 Schichten in vier Runden im Auswahltest.
- **Priorität:** P2 · **Abhängig von:** E03.02 · **Aufwand:** S
- **Ziel:** Begrenzte Zahl je Runde (konfigurierbar), stratifiziert nach Preisklasse × Ablehnungsgrund (erweitert die bestehende Preisklassen-Streuung), Vorrang für bisher unterrepräsentierte Schichten.
- **Abnahmekriterien:** Bei 200 Kandidaten höchstens N neue Snapshots je Runde; jede vorhandene Schicht erscheint innerhalb von k Runden.

### E03.04 – Alternative Gebote simulieren
- **Status W6: umgesetzt und geprüft.** Vier Gebotsstufen und positives EV-Gebot aus dem zum Entscheidungszeitpunkt verfügbaren Ligamodell. Eigener Zuschlag, fehlender Preis, Gleichstand und mehrdeutige Evidenz erzeugen keinen simulierten Sieg. Zeitliche Zuordnung erfordert Listungszeit, Verkäufer und Auktionsende ±1 Sekunde. Nachprüfung bis 48 Stunden.
- **Priorität:** P2 · **Abhängig von:** E03.01 · **Aufwand:** M
- **Ziel:** Je Snapshot Varianten: Mindestgebot, defensiv, Standard, aggressiv, EV-optimal. Abrechnung mit bekanntem Transfer: gewonnen nur bei Gebot > Gewinnerpreis; Gleichstand = unbekannt; verschwunden ohne Transfer = unbekannt (kein Lernen); kein Käufer (Kickbase-Spieler ohne Gebot) gesondert.
- **Abnahmekriterien:** 1. Varianten zählen als **eine** Stichprobe (ADR-007). 2. Unbekannte Gewinnerpreise werden nie geschätzt. 3. Simulationsgrenze ausgewiesen: „andere Manager hätten anders reagieren können“.

### E03.05 – Alternative Verkaufsstrategien simulieren
- **Status W6: umgesetzt und geprüft.** Sechs vorab definierte Verkaufsregeln auf echtem Zuschlag und hypothetischen Gewinnen. Replay über maximal 14 Updates, Tageswerte aus lokalem Verlauf, Prognosen aus datierten Beobachtungen. Fehlende Tage brechen die Folge ab. Zukunftsänderung und Datenlücke getestet.
- **Priorität:** P2 · **Abhängig von:** E03.04 · **Aufwand:** M
- **Ziel:** Für hypothetisch gewonnene und echte Positionen: Verkauf nach 1/2/3 Updates, Prognose-Ausstieg, Trailing-Stop, Deadline-Verkauf – jeweils **vorab definierte Regel**, Bewertung zum jeweiligen Tageswert × Quote.
- **Abnahmekriterien:** 1. Höchstwert nur als Feld `diagnostic_peak`, nie als Ergebnis einer Strategie. 2. Kein Zukunftswissen: Regel entscheidet je Tag nur mit Werten bis zu diesem Tag (Test: geänderte Zukunft ändert Entscheidung nicht).

### E03.06 – Entgangene Gewinne und vermiedene Verluste
- **Status W6: umgesetzt und geprüft.** Je Auktion ein Standardgebot mit zwei Updates als feste Referenz. Gruppierung nach Grund, Ausgang und Finanzierbarkeit mit Anzahl, Summe und Median. Bestätigte Verkäufe separat. 30 Tage, neueste 500 Entscheidungen.
- **Priorität:** P2 · **Abhängig von:** E03.05 · **Aufwand:** S
- **Ziel:** Ergebnisarten getrennt: realisiert, hypothetisch einzeln, vermiedener Verlust, unbekannter Ausgang, nicht finanzierbar, hypothetisch finanzierbar. Je Reason Code: Summe, Anzahl, Median.
- **Abnahmekriterien:** Keine Summe einzelner Hypothesen wird als erreichbarer Gesamtgewinn bezeichnet (gemeinsam realisierbar erst mit E09).

### E03.07 – Lerngewichtung und Deduplizierung
- **Status W6: umgesetzt und geprüft.** Separates diagnostisches Lernmodell für belegte Zuschläge und finanzierbare Standardgebote. Ein Schlüssel je Auktion, reale Evidenz zuerst, Halbwertszeit 30 Tage, volle Stützung ab zehn Auktionen. Keine Übernahme in Handelsparameter.
- **Priorität:** P2 · **Abhängig von:** E03.06 · **Aufwand:** S
- **Ziel:** Gewicht nach Alter, Echtheit (echt 1,0, Schatten ≤ 0,5), Stichprobe; je Auktion höchstens einmal in Lernverfahren.

### E03.08 – Aufbewahrung und Performance
- **Status W6: umgesetzt und geprüft.** Aufbewahrung je Liga 7–365 Tage (Standard 120). Atomare Verdichtung je Nutzer, Liga, Berliner Marktwerttag, Grund und Preisklasse. Pro Runde höchstens 256 Löschungen je Detailtabelle. SQLite-Test: 100.000 Alt-Snapshots, 15,5 ms inklusive Commit für einen Batch. Größenordnung bei angenommenen 40 neuen Auktionen je Liga/Tag: 87.600 pro Jahr, 28.800 gleichzeitig bei 120 Tagen. Bei angenommenen 1–3 KiB je vollständiger Entscheidung ca. 28–84 MiB Detailbestand zuzüglich Tagesaggregate, WAL und freier Seiten.
- **Priorität:** P2 · **Abhängig von:** E03.01 · **Aufwand:** S
- **Ziel:** Konfigurierbare Aufbewahrung (Standard 120 Tage wie heute), danach Verdichtung in Tagesaggregate je Liga × Code × Preisklasse; Löschlauf in Batches.
- **Abnahmekriterien:** DB-Wachstum bei 6 Ligen × 1 Jahr geschätzt und dokumentiert; Löschlauf < 1 s auf 100.000 Zeilen (SQLite).

### E03.09 – Shadow-Dashboard
- **Status W6: umgesetzt und geprüft.** Authentifizierte, liga- und nutzergebundene Lese-API und Dashboard auf der Automatikseite. Angezeigt werden Evidenz, Ergebnisse je Grund, Vergleich der Gebote und sechs Verkaufsregeln; Einstellungen für Aufbewahrung und Stichprobenlimit sind im Formular verfügbar. Leerer Datenbestand ist ein eigener Zustand.
- **Priorität:** P3 · **Abhängig von:** E03.06 · **Aufwand:** M
- **Ziel:** Beobachtete Auktionen, verpasste Chancen, vermiedene Verluste, Gründe, alternative Gebote/Haltedauern, mit deutlicher Kennzeichnung „hypothetisch“.
