# Release- und Rollback-Strategie

## 1. Umgebungen

| Umgebung | Quelle | Image-Tag | Zweck |
|---|---|---|---|
| Development | lokal, `KBI_DEMO=true` | – | Entwicklung, nur DemoWorld/Mock |
| Preview | Push auf `codex/autotrader-3` (oder Paket-Branch) | `ghcr.io/<owner>/kickbase-insights:codex-autotrader-3` und `:sha-<kurz>` | Test auf TrueNAS in einer **separaten** App-Instanz mit **eigener Datenbank** (Kopie), Trader nur Probelauf |
| Stable | Merge nach `main` | `:latest` + `:sha-<kurz>` | Produktion |

Die Tags entstehen automatisch durch `.github/workflows/build.yml` (`type=ref,event=branch`, `type=sha`, `latest` nur auf `main`). **Jeder Push veröffentlicht ein Image** (KI-24) – Push nur bewusst.

**Empfehlung TrueNAS:** produktiv nicht `latest`, sondern `sha-<kurz>` des freigegebenen Commits pinnen. Rollback = vorherigen Tag eintragen. (Entscheidung beim Auftraggeber, MASTERPLAN §7 Frage 7.)

## 2. Checkliste je Release

Vor dem Merge:
- [ ] Alle Pakete des Release `done` (Definition of Done in `AGENTS.md`).
- [ ] CI grün (backend, frontend, ui-audit) für genau diesen Commit.
- [ ] `CHANGELOG.md` ergänzt (Paket-IDs, Verhaltensänderungen, neue Flags mit Standard `off`).
- [ ] Version gehoben (`backend/core/version.py`, `backend/pyproject.toml`, `build-args VERSION` in `build.yml`) – ADR-009.
- [ ] Neue Flags stehen auf `off`; kein Paket aktiviert sich selbst.
- [ ] Migration? → Abschnitt 3 vollständig.
- [ ] `PROJECT_STATE.md` aktualisiert.

Nach dem Update (TrueNAS):
- [ ] App startet, `/api/health` ok, Log ohne Fehler (`Database ready`).
- [ ] Automatik-Seite: Dashboard zeigt letzte Runde, Trader-Schalter unverändert.
- [ ] Eine Runde abwarten: Debug-Protokoll enthält neue Felder, keine unerwarteten Aktionen.
- [ ] Bei Handelsänderungen: Liga zuerst `shadow`, Auswertung nach ≥ 2 Spieltagen, dann `dry_run`, dann `live` in **einer** Liga.

## 3. Datenbankmigrationen

- [ ] **Backup vor dem Update:** SQLite: Container stoppen, `kickbase.db` im Datenverzeichnis (`KBI_DATA_DIR`) kopieren; oder Online-Backup (`sqlite3 kickbase.db ".backup kickbase-<datum>.db"`). PostgreSQL: `pg_dump`.
- [ ] Migration getestet: `check_trader_migration.py` gegen das aktuelle Stable-Release + Test des neuen Migrationsschritts.
- [ ] `init_db` zweimal hintereinander ohne Fehler/Duplikate.
- [ ] Downgrade-Verhalten dokumentiert: `init_db` lehnt eine **neuere** Schema-Version ab („created by a newer Kickbase Insights“). Ein Rollback nach einer Schema-Migration braucht daher das Backup **oder** einen Migrationsschritt, der rückwärtskompatibel bleibt. → Schemaänderungen nur additiv und mit Backup.

## 4. Rollback

| Fall | Vorgehen |
|---|---|
| Neue Funktion verhält sich falsch | Flag der Liga auf `off` (ab E02.08 ohne Neustart). Sofort, kein Deployment |
| Strategie-Konfiguration falsch | Ältere Konfigurationsversion aktivieren (ab E02.07) |
| Gelernte Werte falsch | `POST /api/automation/trader/reset` oder Rückimport der Vorher-Werte aus Ereignis `trader-import` |
| Release fehlerhaft, ohne Schema-Migration | TrueNAS-Image auf vorherigen `sha-`Tag. Neue Tabellen (ADR-010) bleiben ungenutzt liegen. Neue Liga-Optionen (z. B. `sell_ratio`) bleiben gespeichert, aber die alte Version kennt sie nicht und **verwirft sie beim nächsten Speichern der Einstellungen**. Nach dem Zurückwechseln also erneut setzen. |
| Release fehlerhaft, mit Schema-Migration | Container stoppen, Backup zurückspielen, vorherigen Tag starten. Seit dem Backup getätigte echte Transfers bleiben bei Kickbase; der Abgleich (`_settle`) holt den Stand nach, Trades seit dem Backup fehlen im lokalen Log (dokumentieren) |
| Notfall | Server-Schalter `KBI_AUTOMATION__TRADER=false` oder Liga-Schalter „Autotrader“ aus |
