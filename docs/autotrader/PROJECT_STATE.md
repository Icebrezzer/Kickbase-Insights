# Projektstatus Auto-Trader 3.0

**Zuletzt aktualisiert:** 27.11.2026 · **Branch:** `codex/autotrader-3` (lokal, nicht gepusht) · **Basis:** `4b85715` (`codex/autotrader-2-audit`, CI grün)

## Welle 6 · Branch `codex/autotrader-3-w6`

E03.03–E03.09 umgesetzt und lokal geprüft. Paketstände, Messwerte, Einschränkungen und Integrationsanleitung in [WAVE6_HANDOVER.md](WAVE6_HANDOVER.md). Die folgende Kurzfassung beschreibt die gemeinsame Basis vor Welle 5 und 6.

## Kurzfassung

- **Erledigt:**
  - **E00** (Projektvorbereitung)
  - **E01.01** (Exporte analysiert)
  - **E01.00** (Debug-Liquidation)
  - **E01.04** (Maximalgebot gegen freigegebenes Budget, nur Backend)
  - **E06.00** (Verkaufsquote als Liga-Option)
  - **E05.08** (Formationswechsel nach Punkten)
  - **E01.02** (einheitliche Ablehnungscodes)
  - **E10.00** (Prognosegüte auf allen beobachteten Spielern)
- Ohne geänderte Einstellungen handelt der Trader **wie bisher**. Die neuen Optionen `sell_ratio` (Standard 90) und `upgrade_cross_position` (Standard aus) wirken erst nach dem Einschalten je Liga.
- **Welle 2 abgeschlossen:** E01.03 ✅, E02.01 ✅, E02.02 ✅, E02.08 ✅, E01.05 ✅.
- **Welle 3 abgeschlossen:** E02.03 ✅, E02.04 ✅, E02.05 ✅, E03.01 ✅, E03.02 ✅.
- **Welle 4 umgesetzt:** E05.02 ✅, E04.01 ✅, E04.03 ✅, E04.04 ✅, E04.05 ✅, E04.06 ✅, E04.10 ✅. Alles steht hinter den Flags `flexible_bench`, `scenario_credit`, `conditional_repayment` und `upgrade_financing`, Standard aus.
  - Empfohlene Freigabe: erst `shadow` (≥ 2 Spieltage beobachten), dann `dry_run` in einer Probelauf-Liga, dann `live` in einer Liga.
  - Upgrade-Finanzierung braucht die automatische Aufstellung.
  - Offen in E04: E04.02 (P2), E04.07–E04.09, E04.11 (UI).
- **Tipp:** Flag `decision_snapshots` je Liga auf `shadow` stellen, dann sammelt der Trader ab sofort Daten für E03.04–E03.06 (verpasste Chancen). Danach Welle 3: E02.03/E02.04 (Konfiguration speichern, Übernahme ohne Neustart), E03.01/E03.02 (Entscheidungs-Snapshots).
- **CI:** `6250f20` (Welle 1), `d4066f0` (Welle 2), `cedcdab` (ui-audit mit Trader-Runde) und `4709dae` (Welle 3, Lauf 46078231360) vollständig grün: Backend, Frontend, ui-audit, Image. Vorschau-Image `ghcr.io/icebrezzer/kickbase-insights:codex-autotrader-3`. Danach E02.01 → E02.02 → E02.08 → E05.02 → E04 (MASTERPLAN §3 und §9, ADR-012).
- **Geklärt (27.11.2026):** Kickbase zahlt beim Sofortverkauf 100 % des Marktwerts. Formationswechsel mit mehr Punkten sind erwünscht.

## Ergebnis der Export-Analyse (Details `KNOWN_ISSUES.md` B)

In der Liga ohne Käufe gibt es drei Ursachen, und keine davon ist in erster Linie die Kreditberechnung:
1. **Verkaufsquote 0,9** (inzwischen geklärt: Kickbase zahlt 100 %, Option `sell_ratio`): Kein steigender Spieler war in 2 Tagen netto positiv. Die Gewinnschwelle liegt bei über 11 % Anstieg in 2 Updates, der Median der Prognosen bei 3 %.
2. **Qualitätsvergleich über Positionen:** 162 von 307 abgelehnten Elf-Verbesserungen fallen darunter.
3. **Reserve (2 Mio.) über dem Kontostand** und `credit_mode` 1: Der Gewinnhandel hat kein Geld.

## Commits auf `codex/autotrader-3`

| Commit | Paket |
|---|---|
| `ac0bb18` | E00 Projektvorbereitung, Smoke-Test-Korrektur |
| `2e6f6ce` | E01.01 Export-Analyse |
| `263bfa0` | E01.00 Debug-Liquidation |
| `5a180be` | E01.04 `money_check` |
| `6c0bc16` | E06.00 `sell_ratio`, E05.08 `upgrade_cross_position` |
| `3ac2a78` | E01.02 Ablehnungscodes |
| `637244b` | E10.00 Prognosegüte |

## Testlage (27.11.2026, lokal Windows/Python 3.12)

Volle Backend-Suite 17/17 grün: Ruff, 12 Skripte aus der CI, Migration gegen `ebf50d3` und Export-Analyse. `check_trader_safety` hat jetzt 1494 Checks, neu sind `check_trader_reasons` (29) und `check_trader_forecast_quality` (16); die Suite umfasst 17 Prüfungen. Frontend und ui-audit wurden **nicht lokal ausgeführt** (kein Node). Die CI ist für diese Commits **noch nicht gelaufen** (nicht gepusht).

## Epic-Status

| Epic | Status | Nächster Schritt |
|---|---|---|
| E00 | done | – |
| E01 | in_progress: .00, .01 und .04 done | E01.02, dann E01.03, E01.05 (UI), E01.06 |
| E02 | ready | E02.01 |
| E03 | todo | wartet auf E01.02, E02.04 |
| E04 | todo | wartet auf E02.08 (E01.04 ✓, E05.08 ✓) |
| E05 | E05.08 done (als Liga-Option) | E05.02 nach E02.04 |
| E06–E11 | todo | siehe Matrix; E06.04 jederzeit |

## Offene Entscheidungen beim Auftraggeber

1. MASTERPLAN §7, weitere Punkte: Risikobereitschaft, Ersatzbank-Standard, globales Lernen, Release-Rhythmus und Tag-Pinning, SQLite oder PostgreSQL.

## Für die nächste KI

1. `AGENTS.md` lesen, dann dieses Dokument, dann `workpackages/E01-diagnose.md` → E01.02.
2. Lokal: `py -3.12 -m venv`, `pip install ./backend ruff`, Tests wie in `AGENTS.md` §4.
3. Nichts pushen ohne Auftrag (jeder Push baut ein Image).
4. Nach jedem Paket: Eintrag im Paket (Ergebnis, Commit), diese Datei, `CHANGELOG.md`.

- E03.03 (W6): Gewichtete Auswahl nach Preisklasse und Hauptgrund aus dem Bestand des Nutzers in der Liga. Limit 1–200, Standard 32. Bestandspflege verbraucht keine Plätze. 200 Kandidaten, 20 Schichten in vier Runden im Auswahltest.

- E03.04 (W6): Vier Gebotsstufen und positives EV-Gebot aus dem zum Entscheidungszeitpunkt verfügbaren Ligamodell. Eigener Zuschlag, fehlender Preis, Gleichstand und mehrdeutige Evidenz erzeugen keinen simulierten Sieg. Zeitliche Zuordnung erfordert Listungszeit, Verkäufer und Auktionsende ±1 Sekunde. Nachprüfung bis 48 Stunden.

- E03.05 (W6): Sechs vorab definierte Verkaufsregeln auf echtem Zuschlag und hypothetischen Gewinnen. Replay über maximal 14 Updates, Tageswerte aus lokalem Verlauf, Prognosen aus datierten Beobachtungen. Fehlende Tage brechen die Folge ab. Zukunftsänderung und Datenlücke getestet.

- E03.06 (W6): Je Auktion ein Standardgebot mit zwei Updates als feste Referenz. Gruppierung nach Grund, Ausgang und Finanzierbarkeit mit Anzahl, Summe und Median. Bestätigte Verkäufe separat. 30 Tage, neueste 500 Entscheidungen.

- E03.07 (W6): Separates diagnostisches Lernmodell für belegte Zuschläge und finanzierbare Standardgebote. Ein Schlüssel je Auktion, reale Evidenz zuerst, Halbwertszeit 30 Tage, volle Stützung ab zehn Auktionen. Keine Übernahme in Handelsparameter.

- E03.08 (W6): Aufbewahrung je Liga 7–365 Tage (Standard 120). Atomare Verdichtung je Nutzer, Liga, Berliner Marktwerttag, Grund und Preisklasse. Pro Runde höchstens 256 Löschungen je Detailtabelle. SQLite-Test: 100.000 Alt-Snapshots, 15,5 ms inklusive Commit für einen Batch. Größenordnung bei angenommenen 40 neuen Auktionen je Liga/Tag: 87.600 pro Jahr, 28.800 gleichzeitig bei 120 Tagen. Bei angenommenen 1–3 KiB je vollständiger Entscheidung ca. 28–84 MiB Detailbestand zuzüglich Tagesaggregate, WAL und freier Seiten.

- E03.09 (W6): Authentifizierte, liga- und nutzergebundene Lese-API und Dashboard auf der Automatikseite. Angezeigt werden Evidenz, Ergebnisse je Grund, Vergleich der Gebote und sechs Verkaufsregeln; Einstellungen für Aufbewahrung und Stichprobenlimit sind im Formular verfügbar. Leerer Datenbestand ist ein eigener Zustand.

- E03.04 (W6): Zusätzlicher Regressionstest: Sobald sich zwei bekannte Listungen desselben Spielers am Zuschlagszeitpunkt überschneiden, bleibt die Zuordnung unbekannt. Ein Transfer kann damit keine zwei Stichproben liefern.
