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
