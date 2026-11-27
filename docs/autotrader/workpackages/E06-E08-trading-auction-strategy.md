# E06 – Trading Intelligence · E07 – Auction Intelligence · E08 – Strategy Intelligence

## E06 – Trading Intelligence

### E06.00 – Verkaufsquote als Liga-Option (neu, aus E01.01)
- **Priorität:** P1 · **Status:** done · **Aufwand:** S · **Flag:** Option `sell_ratio` (Standard 90 = altes Verhalten)
- **Ergebnis:**
  - `core/trader.py::sell_ratio(opts, learned)` ersetzt die feste Kappung `SAFE_SELL_RATIO = 0,9`. Eine gelernte Quote senkt nur.
  - Verwendet in Planung, Risk Engine, Liquidation/Kredit, Rettung, Ausstieg, Schattenabrechnung (Quote des Schatten-Besitzers) und Backtest.
  - API-Schema, Typen und Automatik-Seite ergänzt; Profile ändern die Quote nicht.
  - Nachrechnung beider Exporte: Mit 100 % bestehen 8 (A) bzw. 4 (B) Gewinnkandidaten Marge und Rendite, mit 90 % keiner.
  - In Liga A bleibt der Gewinnhandel trotzdem ohne Geld, solange Reserve > Kontostand und `credit_mode` 1 gelten (`money_check` zeigt es).
- **Rollback:** Option auf 90.

### E06.04 – Tatsächliche Verkaufsquoten auswerten (zuerst in E06)
- **Priorität:** P1 · **Abhängig von:** E00 · **Aufwand:** S · **Flag:** – (nur Auswertung)
- **Ausgangssituation:** Quote = Median aller Sofortverkäufe aller Nutzer/Ligen, ohne Mindeststichprobe, gekappt bei 0,9 (KI-12).
- **Ziel:** Auswertung je Liga und global: n, Median, 10.-/25.-Perzentil, Abhängigkeit von Preisklasse und Tageszeit; drei Quoten `expected`, `conservative`, `pessimistic` mit Mindeststichprobe (Vorschlag 10), sonst 0,9 / 0,9 / 0,85.
- **Abnahmekriterien:** 1. Keine Erhöhung der genutzten Quote in diesem Paket (nur berechnen, anzeigen, im Debug). 2. Liga-Trennung getestet. 3. Datengrundlage im Dashboard sichtbar.
- **Folgepaket:** Nutzung der Quoten in E04.03 (pessimistisch) und für die Rendite (erwartet) – nur mit empirischer Grundlage (Übergabe §12.3).

### E06.01 – Variable Prognose- und Haltedauer
- **Priorität:** P2 · **Abhängig von:** E03.05, E02.01 · **Aufwand:** M · **Flag:** `variable_hold`
- **Ziel:** `hold_updates` je Kandidat aus Prognoseverlauf (1–5 Updates) wählen, begrenzt durch Deadline und Kapitalbedarf; Grundlage sind die Schattenergebnisse aus E03.05.

### E06.02 – Opportunitätskosten
- **Priorität:** P2 · **Abhängig von:** E06.01 · **Aufwand:** S
- **Ziel:** Kennzahl „Netto je gebundenem Euro und Update“ für gehaltene Positionen und Kandidaten auf derselben Skala (`profit_rank` erweitert), inkl. Kaderplatz als knappe Ressource.

### E06.03 – Intelligente Kapitalrotation
- **Priorität:** P2 · **Abhängig von:** E06.02, E04.06 · **Aufwand:** M · **Flag:** `capital_rotation`
- **Ziel:** Neuer Ausstiegsgrund `ROTATE`: Verkauf, wenn realistisch besserer Kandidat existiert **und** dessen Zuschlag finanziert ist **auch wenn die Auktion verloren geht** (Rotation darf nicht im leeren Kapital enden). Unsicherheit des Zuschlags fließt als P(win) ein.

### E06.05 – Flexible Ausstiegsstrategien
- **Priorität:** P3 · **Abhängig von:** E03.05 · **Aufwand:** S
- **Ziel:** Exit-Parameter (Trailing, Positions-Stop, Zeitlimit, `TURN_SHARE`) aus Schema; Auswahl der Ausstiegsregel je Rolle.

### E06.06 – Rendite pro Kapital und Zeit
- **Priorität:** P3 · **Abhängig von:** E06.02 · **Aufwand:** S
- **Ziel:** Statistik je Position und Strategie: Rendite je Euro, je Tag, je Update (Dashboard, Export).

### E06.07 – Portfolioübergreifende Transferpriorisierung
- **Priorität:** P3 · **Abhängig von:** E06.03, E05.01 · **Aufwand:** M
- **Ziel:** Gemeinsame Rangfolge sportlicher und finanzieller Ziele über eine Nutzenfunktion mit Saisonphasengewichten (E08.02); ersetzt die feste Tier-Reihenfolge nur bei aktivem Flag.

## E07 – Auction Intelligence

### E07.01 – Ligaspezifische Auktionsstatistiken
- **Priorität:** P2 · **Abhängig von:** E00 · **Aufwand:** S
- **Ziel:** Je Liga: Aufschläge je Preisklasse/Position/Wochentag/Tageszeit, n je Zelle, Anteil Auktionen ohne bekannten Gewinner; Anzeige im Dashboard.

### E07.02 – Erweiterte Zuschlagswahrscheinlichkeit
- **Priorität:** P2 · **Abhängig von:** E07.01, E03.04 · **Aufwand:** M
- **Ziel:** `win_probability` mit Glättung über benachbarte Preisklassen und Zeitgewichtung; Kalibrierungsprüfung (vorhergesagte vs. beobachtete Quote, zeitlich getrennt).
- **Abnahmekriterien:** Kalibrierungsfehler auf Holdout nicht schlechter als das 2.0-Modell, sonst bleibt 2.0.

### E07.03 – Gegnerprofile
- **Priorität:** P3 · **Abhängig von:** E07.01 · **Aufwand:** M
- **Ziel:** Je Manager beobachtbare Kennzahlen (Kaufhäufigkeit, typischer Aufschlag) **nur** aus Transfers und `AuctionLog`; keine erfundenen Kontostände/Absichten. Mindeststichprobe je Profil.

### E07.04 – Dynamische Gebotsaufschläge
- **Priorität:** P3 · **Abhängig von:** E07.02 · **Aufwand:** S
- **Ziel:** Wert des Zuschlags (`worth`) nach sportlicher/finanzieller Bedeutung, Vermeidung unnötiger Aufschläge (Grenznutzen-Prüfung im Gebotsraster).

### E07.05 – Auktionszeitpunkte bewerten
- **Priorität:** P3 · **Abhängig von:** E07.01 · **Aufwand:** S
- **Ziel:** Einfluss von Restlaufzeit und Tageszeit auf Aufschlag messen; Gebotszeitpunkt-Empfehlung nur, wenn statistisch belastbar.

## E08 – Strategy Intelligence

### E08.01 – Deklaratives Regelwerk
- **Priorität:** P2 · **Abhängig von:** E02.04 · **Aufwand:** M · **Flag:** `rules`
- **Ziel:** `core/rules.py`: Bedingungen aus fester Metrikliste (Stunden bis Deadline, Kontostand, Teamwert, Prognosegüte, Tage ohne Kaufvorschlag, verletzte Starter, Saisonphase) mit `>=,<=,==`; Aktionen nur „setze Schemafeld in Grenzen“ oder „löse Diagnose aus“. Auswertung einmal je Runde, Ergebnis + angewandte Regeln im Debug.
- **Sicherheit:** S13 – kein `eval`, keine Ausdrücke; Test: Regel mit unbekannter Metrik/Ziel wird beim Import abgelehnt.

### E08.02 – Saisonabhängige Strategie
- **Priorität:** P3 · **Abhängig von:** E08.01 · **Aufwand:** S
- **Ziel:** Saisonphase aus Spieltag/verbleibenden Spieltagen; Gewichtstabelle (Übergabe §14) als Standardregeln, konfigurierbar.

### E08.03 – Mannschaftswertabhängige Strategie
- **Priorität:** P3 · **Abhängig von:** E08.01 · **Aufwand:** S

### E08.04 – Dynamische Zielgewichtung
- **Priorität:** P3 · **Abhängig von:** E08.02, E06.07 · **Aufwand:** M

### E08.05 – Automatische Strategieprofile
- **Priorität:** P3 · **Abhängig von:** E10.03 · **Aufwand:** S
- **Ziel:** Profilvorschlag je Liga aus Ligamerkmalen und Champion-Challenger-Ergebnissen; nur Vorschlag (S14).
