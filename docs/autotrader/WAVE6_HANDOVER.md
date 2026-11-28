# Welle 6 · Shadow Intelligence

Stand 28.11.2026, Repository `Icebrezzer/Kickbase-Insights`, Branch `codex/autotrader-3-w6`, Auftragsbeginn bei `67fb8c7`. Gemeinsame Basis mit W5 ist `0ca9a46`. Dieser Bericht beschreibt den isolierten W6-Stand. Gegenstand sind E03.03 bis E03.09. E06.04 und die Portfolio-Simulation E09 gehören zu anderen Arbeitspaketen.

## Ergebnis und Paket-Commits auf GitHub

| Paket | Commit | Implementierung und Abnahme |
|---|---|---|
| E03.03 | `90dd617` | Persistierte Häufigkeiten je Nutzer/Liga, Preisklasse und erstem Grund steuern die Auswahl. Standard 32 neue Auktionen pro Runde. Bestehende Datensätze behalten ihre erste Entscheidung. Tests mit 200 Kandidaten, wechselnder Reihenfolge und wiederholten Runden. |
| E03.04 | `4b590d3` | Mindestgebot, defensives, Standard- und aggressives Gebot sowie ein EV-Gebot bei ausreichender Ligahistorie und positivem Erwartungswert. Varianten werden vor der Abrechnung eingefroren. Ein gegnerischer Gewinnerpreis muss strikt unter dem jeweiligen Gebot liegen. Gleichstand, fehlende Preise, Fremdligen und Zuordnungskonflikte sind unbekannt. Ein explizit bei Ablauf gebotsloser Kickbase-Spieler hat einen eigenen Ausgang. |
| E03.05 | `c42bf23` | Tageswert × eingefrorene Verkaufsquote bei Verkauf nach einem, zwei oder drei Updates, Prognose-Umschwung, Trailing-Stop oder Spieltagsdeadline. Replay für beobachtete echte Käufe und hypothetische Gewinner. Der Höchstwert dient nur als Diagnose. Zukunftsänderungen verändern frühere Ausstiege im Regressionstest nicht. |
| E03.06 | `9c074de` | Anzahl, Summe und Median je Grund, Ausgang und finanziellem Status. Ein Standardgebot mit zwei Updates liefert pro Auktion genau ein Referenzergebnis. Bestätigte Verkäufe mit bekanntem Erlös und Ergebnis haben ihre eigene Kennzahl. |
| E03.07 | `d952441` | Gewichtete Zuschlagsquote als diagnostischer Lernwert. Echte Beobachtung vor hypothetischer Alternative, maximal ein Lernbeitrag je Auktion und Nutzer/Liga. Maximalgewicht 1 bzw. 0,5, Halbwertszeit 30 Tage, linearer Vertrauensfaktor bis zehn unabhängige Auktionen. Der Wert ändert keine Handelsparameter. |
| E03.08 | `5ecd4a3` | Standard 120 Tage Detailhaltung, konfigurierbar 7–365. Ein Lauf verdichtet höchstens 256 Entscheidungen atomar nach Nutzer, Liga, Berliner Marktwerttag, erstem Grund und Preisklasse. Das Archiv hält Anzahl und Ausgangsverteilung. Ein voller Batch lässt den nächsten Lauf in der nächsten Runde zu. |
| E03.09 | `19effd8` | Dashboard auf der Automatikseite, lesende API mit Nutzer aus authentifizierter Sitzung und autorisierter Liga. Gebots- und Verkaufsvergleiche, Entscheidungsgründe, Finanzierbarkeit und ausgewiesene unbekannte Ergebnisse. Optionen für Stichprobenlimit und Aufbewahrung bleiben beim Profilwechsel erhalten. |

Der QS-Commit `783b9ac` ergänzt die Priorität belegter eigener Auktionsverluste, die Beschränkung der Übersichtskennzahlen auf finanziell mögliche Einzelfälle, Browserprüfungen der befüllten Ansicht und den Benchmark mit zugehörigen Analysezeilen. Commit `da7ad0d` schließt überlappende Wiederlistungen von der Transferzuordnung aus.

## Testergebnisse

| Prüfung | Ergebnis |
|---|---|
| Backend und Werkzeuge | Ruff grün. Sämtliche Standalone-Prüfungen aus `backend/tests` und der isolierte Exportanalyse-Test erfolgreich. Darunter 2.105 Sicherheits-, 629 Finanzierungs-, 53 Lern-, 19 Backtest- und 36 Audit-Regressionsprüfungen. |
| W6 | 12 erfolgreiche Tests. Darunter Wiederanlauf, Nutzer-/Ligatrennung, 200 Kandidaten, Gleichstand, explizit kein Käufer, konkurrierende Transfers, Wiederlistung, tatsächlicher Verlust trotz hypothetischem Zuschlag sowie Rollback und Wiederholung eines Archivbatches. |
| PostgreSQL | Fünf W6-Speicher- und Integrationstests zusätzlich auf einer temporären PostgreSQL-16.2-Instanz mit UTF-8. |
| Demo-Integration | Anmeldung, API und Trader-Runde erfolgreich. Mit und ohne Snapshot-Flag gleiche Aktionsfolge, identische Spieler und Preise. Der instrumentierte Planungsaufruf bei eingeschaltetem Flag sendete null HTTP-Aufrufe über den Kickbase-Client. |
| Migration und Rückwärtskompatibilität | SQLite-Migration von `ebf50d3` und vom direkten Vorgänger `67fb8c7`. Einstellungen, Lernwerte, Trades und Papiergeschäfte blieben erhalten. Der Vorgänger öffnete die W6-Datenbank und las einen dort angelegten Snapshot. Die beiden zusätzlichen Tabellen benötigen keinen Schema-Versionssprung. |
| Frontend | TypeScript-/Vite-Produktionsbuild und alle fünf Frontend-Tests erfolgreich. Lokale Chromium-Regressionssuite mit 30 Routen-/Viewport-Kombinationen und vier zusätzlichen Prüfungen, einschließlich gefülltem Dashboard auf 390 und 1.440 px. Keine festgestellten JS-Fehler oder horizontalen Überläufe. |
| Rundenperformance | Je 20 Demo-Planungen. Flag aus: Median 172,44 ms / 49 SQL-Anweisungen. Flag shadow: 183,85 ms / 51 SQL-Anweisungen. Differenz +6,6 % / +2 Anweisungen. Beide Läufe zusätzlich mit je 240 API-Anfragen bei acht parallelen Clients, null Fehler. Das ist eine lokale Stichprobe ohne fälligen großen Abrechnungsrückstand. |
| Aufbewahrung | SQLite mit 100.000 abgelaufenen Snapshots **und** 100.000 Analysezeilen. Ein Produktionsbatch mit 256 Paaren, Aggregation und Commit in 18,9–27,3 ms. Das Ein-Sekunden-Budget bezieht sich auf eine Wartungstransaktion. Ein Rückstand von 100.000 benötigt 391 Batches. |

Zum Wiederholen die Backend- und Frontendbefehle aus `AGENTS.md` sowie folgende Befehle aus `backend/` verwenden:

```sh
python -m unittest discover -s tests -p 'check_shadow*.py' -v
python tests/benchmark_shadow_retention.py
python tests/benchmark_audit.py
KBI_BENCH_SNAPSHOTS=1 python tests/benchmark_audit.py
```

Die CI führt W6-Tests und Archivbenchmark im Backend-Job aus. Der UI-Audit-Job nutzt den lokalen Demo-Server. Der Image-Job veröffentlicht durch den genehmigten Branch-Push automatisch ein Branch-Image.

## Einordnung der Zahlen und verbleibende Risiken

- Die API `GET /api/automation/trader/shadow-intelligence` betrachtet die jüngsten 500 noch vorhandenen Einzelentscheidungen innerhalb von 30 Tagen. Jede Aufschlüsselung bezieht sich auf diese Stichprobe. Realisierte Verkäufe haben dasselbe Zeitfenster und stammen direkt aus dem Handelsprotokoll.
- „Finanzierbar“ beschreibt den am Entscheidungszeitpunkt für einen einzelnen Kandidaten belegbaren Geldrahmen. Vereinslimit, Kaderplatz und sportliche Gründe stehen daneben. Ein unbekannter Rahmen bleibt unbekannt. Einzelgewinne konkurrieren um dasselbe Kapital. Eine gemeinsame Portfoliorendite erfordert E09.
- Die Zuordnung zu einem Zuschlag erfordert eine belegte Listung und passenden Spieler, Verkäufer, Liga sowie Transferzeitpunkt innerhalb einer Sekunde um das eingefrorene Auktionsende. Bei Zeitversatz, fehlenden Angaben, konkurrierenden Listungen oder fehlendem eindeutigen Transfer bleibt der Ausgang unbekannt. Andere Manager hätten bei anderen Geboten anders reagieren können. Ein eigener Zuschlag verrät den zweithöchsten Preis nicht.
- Das EV-Gebot optimiert den finanziellen Wiederverkaufswert auf dem bestehenden Gebotsraster. Die Aussagekraft hängt von den gespeicherten Vergleichsauktionen ab. Bei unzureichender Historie oder ohne positiven Erwartungswert zeigt die UI „Ohne Modellgebot“.
- Verkaufsregeln beobachten bis zu 14 Updates. Lücken im Tagespreisverlauf beenden den Replay. Fehlende Tagesprognosen erlauben keinen nachträglich konstruierten Prognose-Ausstieg. Bei noch ausstehender Deadline bleibt die Strategie offen. Hypothetische Verkaufsbeträge sind keine bestätigten Einnahmen.
- Bei angenommenen 40 neuen Auktionen je Liga und Tag entstehen über sechs Ligen 87.600 Entscheidungen/Jahr. Mit 120 Tagen Aufbewahrung bleiben etwa 28.800 im Detail. Bei 1–3 KiB je vollständigem Datensatzpaar ergibt das rund 28–84 MiB zuzüglich Tagesarchiv, Datenbank-Freiseiten und WAL. Die kleine Benchmark-Nutzlast ist keine Messung einer Produktivliga. Langzeitvolumen und Anteil eindeutig auflösbarer Auktionen hängen von Aktivität und Sync-Takt ab.
- Ein älterer Snapshot ohne gespeicherte Varianten bleibt lesbar und wird als unbekannt ausgewiesen. Bereits verdichtete Einzelverläufe lassen sich aus den Tagesaggregaten nicht rekonstruieren. Für eine vollständige Wiederherstellung benötigt man das Datenbankbackup vor der Verdichtung.
- Die Sicherheitsprüfungen S1–S10 bleiben im bestehenden Ausführungspfad. W6 speichert Beobachtungen und nutzt lokale Daten (S11/S12). Die Funktionen erzeugen keine Kickbase-Schreibaktionen, Strategiefreigaben oder neuen Kredite (S3/S4/S14). Unvollständige Evidenz bleibt unbekannt (S18). Alle hier beschriebenen Integrationstests liefen mit synthetischen Daten.

## Spätere Integration mit Welle 5

Die rein lesende Konfliktprüfung gegen W5 `bd247a1` ermittelte drei Konfliktdateien. Die Branches wurden bei dieser Abnahme weder zusammengeführt noch auf TrueNAS ausgerollt.

1. **Aktuelle Spitzen feststellen.** Beide Branches neu abrufen. Einen separaten Integrationsbranch von der dann freigegebenen W5-Spitze erstellen. W6 als vollständige Commitfolge übernehmen, einschließlich der Vorarbeiten vor `67fb8c7`. Einzelnes Cherry-Picking nur der sieben Hauptcommits lässt diese Grundlagen und die abschließenden Prüfkorrekturen aus.
2. **Trader-Service zusammenführen.** In `backend/sync/trader.py` W5s `_last_inputs` und `_simulated` sowie W6s `_snapshots_pruned` mit Schlüssel `(user_id, league_id)` erhalten. Die W5-Was-wäre-wenn-Planung darf weder Snapshots noch Beobachtungen, Aggregate oder Debug-Zeilen schreiben. Reguläre Planung übergibt dieselbe versionierte `Options`-Instanz an W6. Den Finanzrahmen gegen W5s Kreditauslastung und Deadline-Regeln nachprüfen.
3. **Formular und Changelog abgleichen.** In `frontend/src/pages/Automation.tsx` müssen `creditUtilization`, `snapshotDays` und `snapshotLimit` in Beschriftungen, Ausnahmen beim Profilwechsel und übernommenen Werten erhalten bleiben. Beide Changelog-Einträge aufnehmen. Automatisch zusammengeführte Änderungen in API-Schemas, Konfigurationsschema und Smoke-Tests ebenfalls prüfen.
4. **Kombination in Demo testen.** Mit allen Flags aus die Aktionsfolge gegen W5 vergleichen. Mit ausschließlich `decision_snapshots=shadow` dieselben Aktionen und null zusätzliche Kickbase-Aufrufe erwarten. Eine W5-Was-wäre-wenn-Anfrage wiederholen und vorher/nachher die Zeilenzahlen in `decisionsnapshot`, `shadowanalysis` und `shadowdaily` vergleichen. W5-Konfigurationsvergleich und Rollback mit beiden neuen Optionen prüfen.
5. **Abnehmen.** Vollständige Backend-, Frontend-, Migrations- und Browserprüfungen auf dem neuen Integrationscommit ausführen. Unbekannte Ergebnisse, Zuordnung bei Wiederlistungen und beide Benchmarks erneut prüfen. Ein späterer Release oder ein Deployment benötigt eine eigene Freigabe.
6. **Rollback.** Für einen sofortigen Stopp der W6-Erfassung und -Verdichtung das Flag `decision_snapshots` in der betreffenden Liga auf `off` stellen. Für einen Versionsrollback den vorher freigegebenen Stand verwenden. Die additiven Tabellen können erhalten bleiben.
