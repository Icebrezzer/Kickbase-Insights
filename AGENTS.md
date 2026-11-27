# AGENTS.md – Arbeitsanweisungen für KI-Agenten

Gilt für jede KI (Claude, Codex, andere), die an diesem Repository arbeitet. Menschen lesen zuerst `README.md` und `DEVELOPMENT.md`.

## 1. Zuerst lesen (in dieser Reihenfolge)

1. `docs/autotrader/PROJECT_STATE.md` – wo das Projekt steht, nächstes Arbeitspaket, Blocker.
2. `docs/autotrader/SAFETY_RULES.md` – nicht verhandelbare Regeln. Gehen allem anderen vor.
3. `docs/autotrader/MASTERPLAN.md` – Ziel, Epics, Reihenfolge, Abhängigkeiten.
4. Das Arbeitspaket in `docs/autotrader/workpackages/E<nn>-*.md`.
5. `docs/autotrader/ARCHITECTURE.md`, bei Bedarf `AUTOTRADER.md` (fachliche Logik von Auto-Trader 2.0).

Der Projektstand steht in diesen Dateien, nicht im Chatverlauf. Wer etwas ändert, aktualisiert sie.

## 2. Arbeitsablauf je Arbeitspaket

READ → PLAN → IMPLEMENT → TEST → REVIEW → DOCUMENT → COMMIT → STATUS → RELEASE.

- **Ein Paket, ein Hauptziel.** Richtwert 100–400 geänderte Zeilen, 2–6 Quelldateien, höchstens eine DB-Migration.
- **Abhängigkeiten zuerst.** Ein Paket beginnt erst, wenn seine Abhängigkeiten den Status `done` haben.
- **Kleinste vollständige Lösung.** Bestehende Funktionen weiterverwenden (`core/trader.py`, `core/risk.py`, `sync/trader.py`). Kein Umbau ohne Paket.
- **Neue Handelslogik nur hinter Feature Flag** (ab E02.08), Standard `off`. Ohne Flag muss das bisherige Verhalten bit-identisch bleiben.
- **Bei Blockern:** Ursache im Paket und in `PROJECT_STATE.md` eintragen, Paket nicht als `done` markieren, nichts erfinden.

## 3. Definition of Done

Alle Abnahmekriterien erfüllt · neue und betroffene Tests grün · Sicherheitsregeln eingehalten · keine Live-Transfers · Performance betrachtet · Daten und Abwärtskompatibilität erhalten · Migration getestet · Flag vorhanden (wenn Handelslogik) · Rollback beschrieben · Doku und `PROJECT_STATE.md` aktualisiert · eigener Commit · CI grün.

**Nicht ausgeführte Tests werden ausdrücklich als „nicht ausgeführt“ markiert.** Ein grüner Lauf ist kein Beweis für Fehlerfreiheit.

## 4. Befehle

Backend (aus `backend/`, Python ≥ 3.12; CI nutzt 3.13):

```
pip install . ruff
ruff check --extend-ignore E501 .
python tests/check_coach.py
python tests/check_trader.py
python tests/check_trader_safety.py
python tests/check_trader_intelligence.py
python tests/check_trader_learning.py
python tests/check_trader_backtest.py
python tests/check_audit_regressions.py
python tests/check_league_preferences.py
python tests/check_wealth.py
python tests/check_locks.py
python tests/check_leader.py
python tests/smoke_manager_tools.py
python tests/check_trader_migration.py <backend-Ordner einer alten Version>   # z. B. git archive ebf50d3 backend
```

Werkzeuge (aus dem Repo-Root): `python -I tools/autotrader/check_analyze_export.py`, Export-Analyse: `python -I tools/autotrader/analyze_export.py export.json`.

Frontend (aus `frontend/`, Node 22): `npm ci`, `npm run build`, `npm test`.

## 5. Harte Grenzen für Agenten

- **Keine echten Kickbase-Transaktionen** während Entwicklung und Tests. Nur `MockTransport`, `DemoWorld` (`KBI_DEMO=true`) oder Probelauf.
- Keine Zugangsdaten, Tokens, `.env`-Inhalte oder echten Nutzer-/Liga-IDs in Commits, Logs, Doku oder Issues.
- **Push nur auf ausdrückliche Anweisung.** Jeder Push löst `.github/workflows/build.yml` aus und veröffentlicht ein Docker-Image mit Branch-Tag; ein Push auf `main` überschreibt `latest`, das TrueNAS zieht.
- Niemals auf `main` committen. Arbeitsbranch für Auto-Trader 3.0: `codex/autotrader-3` (kleine Unterbranches pro Paket sind erlaubt).
- Reale JSON-Exporte des Auftraggebers nicht ins Repository committen (personenbezogen). Ablage außerhalb oder unter einem ignorierten Pfad.
- Sicherheitsmechanismen (Risk Engine, Kill-Switch, Sperren, Leader-Lease, Statusabgleich) werden nie zur Vereinfachung abgeschwächt.

## 6. Konventionen

- Code und Kommentare englisch, Kommentare mit `###` für Abschnitte. Doku und UI deutsch.
- Geldbeträge in ganzen Euro (`int`), Gebotsschritt 10.000 €.
- Zeiten in UTC speichern, Tageslogik in Berlin-Zeit (`analytics.MARKET_VALUE_TIMEZONE`).
- Reason Codes sind stabil, maschinenlesbar, GROSSBUCHSTABEN (`core/risk.py`). Nie umbenennen, nur ergänzen.
- Commits: kurze Zusammenfassung, Paket-ID im Text (z. B. `E01.02: ...`).
