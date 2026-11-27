# E05 – Squad Intelligence

Flag: `flexible_bench` (E05.02/E05.06), `player_roles` (E05.01/E05.05). Bei `off` gilt die 2.0-Ersatzlogik (`missing_cover`, `keeps_cover`, `cover_max_price`).

### E05.01 – Dynamische Spielerrollen
- **Priorität:** P2 · **Abhängig von:** E02.08 · **Aufwand:** M
- **Ziel:** Rollen `core, starter, upgrade, backup, growth, flip, liquidation, watchlist` als Menge je Spieler und Runde (mehrere möglich), abgeleitet aus Zweck des Kaufs (TradeLog), bester Elf, Ersatzbedarf, Finanzplan. Nur Anzeige/Debug in diesem Paket.
- **Abnahmekriterien:** Jeder Kaderspieler hat ≥ 1 Rolle; ein Gewinnspieler, der in der besten Elf steht, ist `flip` + `starter`; Rollen in Debug und Export.

### E05.02 – Konfigurierbare Ersatzbank
- **Priorität:** P1 · **Abhängig von:** E02.04 · **Aufwand:** M
- **Ziel:** `bench.strategy` ∈ `full_cover` (2.0), `minimal` (nur TW + je eine Feldposition), `none_outside_critical` (Ersatz nur in `prepare/repay/final`), `adaptive` (E05.06); `bench.max_total_budget`.
- **Abnahmekriterien:** 1. `full_cover` = 2.0 bit-identisch. 2. Mit `minimal` geben Liquidation und Gewinn-Budget den nicht benötigten Ersatzschutz frei (Test mit Zahlen). 3. In `prepare` gilt immer mindestens die Absicherung der Positionen der besten Elf mit Verletzungsrisiko (S10).

### E05.03 – Spielerbezogene Schutzregeln
- **Priorität:** P2 · **Abhängig von:** E05.01 · **Aufwand:** S
- **Ziel:** Nutzer markiert Spieler als „nie verkaufen“ / „darf verkauft werden“ / „nur Rettung“; Risk Engine respektiert `never_sell` (neuer Code `USER_PROTECTED`).

### E05.04 – Geplante Startelf-Upgrades
- **Priorität:** P2 · **Abhängig von:** E04.05, E05.01 · **Aufwand:** S
- **Ziel:** Watchlist von Upgrade-Zielen mit Finanzierungsplan, sichtbar vor dem Kauf.

### E05.05 – Automatische Rollenwechsel
- **Priorität:** P3 · **Abhängig von:** E05.01 · **Aufwand:** S
- **Ziel:** Flip → Starter, wenn er in die beste Elf rückt (dann gelten Startelf-Schutzregeln statt Exit-Regeln); Ereignis im Log.

### E05.06 – Adaptive Kaderabsicherung
- **Priorität:** P3 · **Abhängig von:** E05.02, E05.07 · **Aufwand:** M
- **Ziel:** Ersatzbedarf je Position aus Formation, Fitness, Einsatzwahrscheinlichkeit, Spieltagsnähe, Kapitalbedarf; fehlende Daten erhöhen den Bedarf (Fail-Closed), nie umgekehrt.

### E05.07 – Erweiterte sportliche Bewertung
- **Priorität:** P3 · **Abhängig von:** E02.01 · **Aufwand:** M
- **Ziel:** Gewichte (Schnitt/Form/Einsatz/kommende Spiele) aus Schema; Kalibrierung mit `ExpectationLog` (zeitlich getrennt). Keine neuen Datenquellen ohne Prüfung ihrer Zuverlässigkeit (Übergabe §11.3).
- **Abnahmekriterien:** Fehlende Daten werden nicht als 0 oder als gut gewertet (Tests je Feld).

### E05.08 – Qualitätsvergleich bei Formationswechsel (neu, aus E01.01)
- **Priorität:** P1 · **Status:** todo – **wartet auf fachliche Entscheidung** · **Abhängig von:** E02.08 (Flag) · **Aufwand:** S · **Flag:** `upgrade_cross_position`
- **Ausgangssituation:** KI-27. In Liga A waren 162 von 307 abgelehnten Elf-Verbesserungen Fälle, in denen der verdrängte Spieler auf einer anderen Position spielt. `lineup_upgrade` vergleicht dann dessen Saisonqualität mit der des Ziels.
- **Ziel:** Bei Formationswechsel gilt nicht der Qualitätsvergleich über Positionen. Gilt stattdessen:
  - (a) Vergleich mit dem schwächsten Starter **gleicher Position** und zusätzlich
  - (b) Punktgewinn der Elf über die nächsten 3 Spiele (`ahead` je Spieler, aufsummiert über die Elf vorher und nachher) ≥ `min_gain`.
- **Nicht enthalten:** Änderung von `min_gain`, `min_play` und `min_avg_edge`.
- **Module:** `core/trader.py::lineup_upgrade`, Tests in `check_trader_intelligence.py`.
- **Sicherheit:** S6 unberührt (kein Verkauf). Flag `off` = altes Verhalten (Determinismus-Test).
- **Abnahmekriterien:**
  1. Nachgerechnete letzte Runde aus Liga A (anonymisierte Testdaten): Der Verteidiger mit +23,5 Punkten wird zum Upgrade.
  2. Ein Einmal-Effekt, also hoher Gewinn nur am nächsten Spieltag und über 3 Spiele schlechter, wird weiter abgelehnt.
  3. Mit Flag `off` sind die Aktionen identisch zu vorher.
- **Pflichttests:** Formationswechsel 3-5-2 → 4-4-2; Wechsel ohne `ahead`-Daten (Fail-Closed: Ablehnung wie bisher).
- **Rollback:** Flag `off`.
