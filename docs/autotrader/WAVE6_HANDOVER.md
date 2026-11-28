# Welle 6 – Entwicklungsstand (WIP)

Branch: `codex/autotrader-3-w6`, Basis `0ca9a46cce577b6699a5f34655cf571c5980df4e`.
Welle 5 bleibt auf dem anderen Branch. Keine Live-Aktivierung, kein Merge, kein Deployment.

## E03.03 / E03.04 – in Arbeit, nicht done

- Reine Auswahlfunktion mit Obergrenze, Deduplizierung und stratifizierter Priorisierung.
- Reine Gebotsvarianten und konservative Auswertung expliziter Auktionsevidenz.
- Keine DB-, Netzwerk- oder Live-Handelszugriffe.
- Varianten sind keine unabhängigen Stichproben; kein Käufer ist ein eigener Ausgang, Gleichstand und fehlende Evidenz bleiben unbekannt.
- Keine Finanzierungsfreigabe; EV-optimales Gebot fehlt noch.

## Tests

Lokal: `cd backend && python -m unittest discover -s tests -p check_shadow_intelligence.py -v` – 4 Tests bestanden, compileall erfolgreich. Repository-weite Tests nicht ausgeführt: Git-Clone in der Testumgebung wegen DNS nicht möglich. CI-Integration des neuen Tests noch offen.

## Nächste Schritte

1. Auswahl nach Ermittlung vorhandener Snapshots in TraderService._snapshot einhängen; alte Zeilen weiterhin aktualisieren. Zählung je Nutzer/Liga, konfigurierbares Limit, coach.price_class.
2. Gebotsvarianten aus eingefrorenen Daten erzeugen, eindeutige Auktionszuordnung und persistierte Ergebnisse ergänzen. Finanzierbarkeit separat ausweisen; keine zusätzlichen Kickbase-Aufrufe.
3. Isolation, Neustart, Persistenz, Flags, unverändertes Live-Verhalten, Benchmark und CI testen.
4. E03.05–E03.09 umsetzen. Gemeinsame Dateien mit Welle 5 erst bei Integration koordinieren.
5. Projektstatus, Arbeitspaketdateien und Changelog bei Abschluss aktualisieren. Keine Pakete vor vollständiger Abnahme als erledigt markieren.
