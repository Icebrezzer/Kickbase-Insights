# Auto-Trader 2.0 – Entwicklungs- und Prüfbericht

Branch `codex/autotrader-2` (von `codex/mobile-manager-redesign`, Stand `ebf50d3`), 25.11.2026.
Die fachliche Beschreibung steht in [AUTOTRADER.md](AUTOTRADER.md). Dieser Bericht beschreibt, was geändert, geprüft und **nicht** geprüft wurde.

---

## 1. Ausgangszustand

Ausgangspunkt war `ebf50d3`, der erste Autotrader. Dazu kamen nicht committete Änderungen aus derselben Sitzung (Kredit, Kaderaufbau, Debug-Export, Layout), die als erste Commits auf diesem Branch gesichert wurden.

Was es gab:
- Gebote für die Startelf, Gewinnhandel und Schattentransfers.
- Lernen gemeinsam für alle Ligen.
- Probelauf als Standard.

Tests: 5 von 6 Backend-Prüfungen bestanden. `check_locks` schlägt unter Windows fehl, weil `fcntl` fehlt (vorbestehend, nicht vom Trader).

## 2. Identifizierte Schwachstellen (im Code bestätigt)

| # | Schwachstelle | Schwere |
|---|---|---|
| 1 | Gewinn ohne Verkaufsquote (`gain − (Gebot − Wert)`): brutto positive, netto negative Käufe | P0 |
| 2 | `bool("false") == True`; `NaN` in den Optionen ließ das Laden **abstürzen** | P0 |
| 3 | Leere Admin-Liste = jeder darf das gemeinsame Lernen überschreiben | P0 |
| 4 | Platz-Verkauf zählte das ungewisse Ziel schon als Ersatz und gab den verdrängten Stammspieler ab | P0 |
| 5 | Erfolgreicher Sofortverkauf und danach ein Fehler beim Kontostand: als „fehlgeschlagen“ gebucht | P0 |
| 6 | Ohne Antwort von Kickbase: kein Abgleich; nach einem Neustart unbekannt | P0 |
| 7 | Probelauf verbrauchte echte Tageslimits, löste Rückkaufsperre und Stop-Loss aus | P0 |
| 8 | Kredit gedeckt durch alle Bankspieler, auch gesperrte und den letzten Ersatz | P0 |
| 9 | Rückzahlung nur ab 1 Std. vor dem Spieltag (bereits behoben, s. 3.) | P0 |
| 10 | Gewinnhandels-Anteil je Gebot statt gesamt | P1 |
| 11 | Prognose über einen beliebigen Haltezeitraum gelernt (Horizont passte nicht) | P1 |
| 12 | Schattenauktion ohne Transfer als „gewonnen“ gelernt, Gleichstand als Sieg | P1 |
| 13 | Unbekannter Erlös fiel auf den Schätzwert zurück, unbekannter Gewinn zählte als 0 € | P1 |
| 14 | Prognose-Vertrauen bis 1,2 (über der Prognose) | P1 |
| 15 | Mindestgewinn auch für Startelf-Lücken (bereits behoben, s. 3.) | P1 |
| 16 | Schattentransfers ohne Nutzerbezug: andere Liga-Mitglieder sahen sie in Ansicht und Export | P1 (Datenschutz) |
| 17 | Lernsperre nur je Prozess | P2 |
| 18 | ISO-Woche in UTC statt Berlin-Zeit | P2 |

## 3. Vor der Bearbeitung schon behoben (in dieser Sitzung)

Diese Punkte sind jetzt durch Regressionstests abgesichert:
- Lücken der Startelf füllen ohne Mindestgewinn, mit echten Punkten.
- Offene Gebote zählen als künftige Spieler.
- Rückzahlung ab dem Vorabend.
- Aufstellungs-Rückmeldung mit `lo`-Plätzen.

## 4. Umgesetzte Korrekturen

Alle Schwachstellen aus 2.; siehe die Commits je Meilenstein (19.).

## 5. Neue Funktionen

**Meilenstein 1:**
- Netto-Gewinn, Mindestrendite, Gebotsobergrenzen.
- Risk Engine mit 20 Begründungscodes.
- Transaktionsstatus mit Abgleich.
- Deadline-Phasen.
- Kredit nur gedeckt durch eine simulierte Verkaufsfolge.
- Notfallregel, automatische Pause nach API-Fehlern.

**Meilenstein 2:**
- Startelf 2.0: Qualitätswert, wenig Daten, die nächsten 3 Spiele, faire Preis-pro-Punkt-Rechnung.
- Prioritäten je Phase.
- Ausstiegssystem: SPORT, STOP, TRAIL, TURN, TAKE, TIME.
- Stop-Loss inklusive Buchverluste.

**Meilenstein 3:**
- Gewinnchance aus den Liga-Auktionen, Gebote nach Erwartungswert.
- Globales Modell plus Liga-Modell.
- Prognose-Pause, Trefferquote.
- Marge nach Ergebnisgröße.
- Strengere Schattenregeln, Versionierung, Reset.

**Meilenstein 4:**
- Walk-Forward-Backtest auf echten Auktionen.
- 5 Strategien im Vergleich, 3 Profile.

**Meilenstein 5:**
- Dashboard „Autotrader jetzt“ mit Begründungen.
- Statistik, Benachrichtigungen, Laufzeitmessung.

**Meilenstein 6:**
- Nutzertrennung der Schattentransfers.
- Prozessübergreifende Lernsperre.
- Migrationstest.
- CI-Schritte, Konfigurationsdoku.

## 6. Geänderte Dateien

**Neu:**
- `backend/core/risk.py`, `backend/core/backtest.py`
- `backend/tests/check_trader_safety.py`, `check_trader_intelligence.py`, `check_trader_learning.py`, `check_trader_backtest.py`, `check_trader_migration.py`
- `AUTOTRADER.md`, `AUTOTRADER_RELEASE.md`

**Geändert:**
- Backend: `backend/core/trader.py`, `backend/sync/trader.py`, `backend/sync/automation.py`, `backend/api/{coach_routes,schemas,insights,context}.py`, `backend/core/config.py`, `backend/db/{models,__init__}.py`
- Tests: `check_trader.py`, `check_league_preferences.py`, `smoke_manager_tools.py`
- Frontend: `frontend/src/pages/Automation.tsx`, `frontend/src/api/{hooks,types}.ts`, Layout-Komponenten (`DataTable`, `ui`, `charts`, `matches`, `Live`, `Status`)
- Sonstiges: `README.md`, `.env.example`, `.github/workflows/build.yml`

Umfang seit `ebf50d3`: 29 Dateien, rund 4.000 Zeilen hinzugefügt und 350 entfernt; dazu die Änderungen aus Meilenstein 6.

## 7. Datenbankmigrationen

Alle Migrationen sind additiv, es gibt keinen Schema-Versionssprung:
- **Neue Tabelle** `traderdebug`.
- **Neue Spalten** `userautomation.trader*` (aus `ebf50d3`) und `shadowtrade.user_id` (Standard `''`).
- **Neue Optionen** liegen im JSON `trader_options`. Fehlende Schlüssel bekommen ihren Standardwert.
- **Lernzustände** tragen `version: 2`. Ältere laden mit Standardwerten. Der bisherige Zustand wird zum globalen Basismodell.
- **Geprüft:** Eine Datenbank aus `ebf50d3` und eine aus `5ddf70c` (vor dem Autotrader) öffnen mit dieser Version. Einstellungen, Gelerntes, Trades und Schatten bleiben erhalten; ein zweiter Start ändert nichts (`tests/check_trader_migration.py`).

## 8. Neue Einstellungen und Standardwerte

| Einstellung | Standard |
|---|---|
| `min_roi` | 2 % |
| `credit_mode` | 1 (Kredit nur für Startelf und Ersatz) |
| `trailing_stop` | 5 % |
| `position_stop` | 10 % |
| `max_hold_days` | 7 |
| `rescue_override` | aus |
| `profit_share` | jetzt kumuliert (60 %) |
| `KBI_AUTOMATION__TRADER_ADMINS` | leer = niemand |

Die Profile Konservativ, Ausgewogen und Offensiv werden nur auf Klick übernommen.

## 9. Architekturentscheidungen

- **Risk Engine als eigene reine Funktion** (`core/risk.py`) statt verstreuter Prüfungen. Sie gilt für Probelauf und Live; der Backtest verwendet dieselben Entscheidungsfunktionen.
- **Kein Ganzzahl-Löser** für die Gebotskombination. Bei 6 Geboten pro Tag ist die gierige Auswahl nach Rendite je Euro nahe am Optimum, und eine ganze Abhängigkeit für wenig Nutzen lohnt nicht.
- **Ein Verkauf pro Runde, danach Neuplanung:** Geplante Verkäufe sind kein Geld. Eine bestätigte Datenlage ist wichtiger als Tempo.
- **Phasen zustandslos aus der Uhr:** Nach einem Neustart ist ohne gespeicherten Zustand sofort die richtige Phase aktiv.
- **Gewinnchance empirisch aus Liga-Transfers:** Kein angelerntes Modell, das ohne Daten etwas behauptet.
- **Backtest nur für den Gewinnhandel:** Was die Daten nicht hergeben, wird nicht simuliert.

## 10. Testergebnisse (Windows, Python 3.13, Demo-Daten)

| Prüfung | Ergebnis |
|---|---|
| `check_trader_safety.py` | 963 / 963 bestanden (inkl. 300 zufällige Pläne als Invarianten) |
| `check_trader_learning.py` | 53 / 53 |
| `check_trader_intelligence.py` | 29 / 29 |
| `check_trader_backtest.py` | 17 / 17 |
| `check_trader.py` | bestanden |
| `check_trader_migration.py` | bestanden (ab `ebf50d3`); `5ddf70c` separat bestanden |
| `smoke_manager_tools.py` | 125 Prüfungen bestanden (Demo-App mit Probelauf, Live-Ausführung, unklarer Status, 429, Rettung, Export/Import, Reset, Nebenläufigkeit, Dashboard, Nutzertrennung) |
| `check_coach.py`, `check_league_preferences.py`, `check_wealth.py` | bestanden |
| `check_locks.py` | **fehlgeschlagen**: vorbestehend, Windows ohne `fcntl`. Unter Linux/CI nicht betroffen |
| Frontend `npm run build` (tsc + vite) | bestanden |
| Browser (Demo, 375–1920 px) | Automatik-Seite, Dashboard, Profile, Backtest geprüft, kein seitliches Scrollen |
| ruff (Backend) | bestanden (E501 ausgenommen, wie im Projekt üblich) |

## 11. Backtest-Ergebnisse

- **Demo-Daten:** Keine Strategie bietet. Der prognostizierte Gewinn aller Demo-Auktionen liegt unter der Mindestmarge, deshalb sind alle Ergebnisse 0 €.
- **Konstruierte Verläufe:** Die alte Regel kauft einen brutto positiven, netto negativen Spieler und verliert. Die neue Regel lässt ihn aus und gewinnt mit einem stark steigenden Spieler. Ein Blick in die Zukunft findet nicht statt.
- **Echte Kalibrierung:** offen. Sie braucht deine Liga: Automatik → „Strategien im Rückblick vergleichen“.

## 12. Performance

- **Eine Runde** dauert in der Demo (15 Kaderspieler, 18 Marktspieler) 0,1–0,15 s und wird je Runde gemessen.
- **Der Backtest** braucht für 64 Auktionen und 3 Zeiträume 0,2 s.
- **Debug-Protokoll:** nur Runden mit Änderungen, 21 Tage aufbewahrt.
- **Nicht gemessen:** viele Ligen gleichzeitig.

## 13. Kickbase-API: Einschränkungen

Ohne Live-Zugang und ohne Dokumentation ist nichts davon verifiziert, alles wird vorsichtig behandelt (Details: AUTOTRADER.md §11):
- 33-%-Regel.
- Abbuchung beim Zuschlag.
- Offene Gebote im Kontostand.
- Sofortverkaufsquote.
- Gleichstand.
- Zurückziehen per `DELETE …/offers/{id}`.
- Format der gespeicherten Aufstellung.
- Punkte bei einem Verkauf nach dem Anpfiff.

## 14. Verbleibende Risiken

- **Serverausfall:** Fällt der Server vom Vorabend bis zur Deadline aus, bleibt ein Minus stehen.
- **Mehrere Container** auf derselben Datenbank planen dieselbe Runde doppelt; die Lernsperre ist sicher, die Rundensperre nicht.
- **Gewichte und Profilwerte** sind nicht kalibriert.
- ~~Zurückziehen von Geboten ist nie gegen Kickbase gelaufen.~~ Behoben und am 25.11. in v3.1.0-mgr.18 bestätigt: Kickbase-Gebote haben keine eigene ID, gelöscht wird mit der Nutzer-ID (`uoid`).
- Das Maximalgebot ist jetzt Kontostand + 33 % Teamwert (abgeglichen mit BaseXI und Kickbases Ablehnung `ThirtyThreePercentRuleExceeded`).
- **Gebot nach Erwartungswert** bei großzügigem `max_cost_per_point` → höhere Startelf-Gebote.

## 15. Offene Aufgaben

- Kalibrierung mit einer echten Liga (Backtest, Probelauf über mindestens 2 Spieltage).
- `check_locks` unter Windows (vorbestehend).
- Mehrere gleichzeitige Gebote je Lücke kurz vor dem Spieltag.
- Kombinatorische Rettung statt gieriger Auswahl.
- Spielminuten und Startelf-Wahrscheinlichkeit, sobald Daten vorliegen.

## 16. Docker-Image und Build

Lokal ist kein Docker installiert, **ein Docker-Build wurde nicht ausgeführt**.
- **Dockerfile:** unverändert und passend. Es gibt keine neuen Abhängigkeiten, nur die Standardbibliothek.
- **Image:** Die CI (`.github/workflows/build.yml`) baut bei jedem Push nach bestandenen Tests ein Image mit dem Branch-Namen als Tag: `ghcr.io/icebrezzer/kickbase-insights:codex-autotrader-2`.
- **Neue CI-Schritte:** Die Trader-Tests laufen jetzt in der CI mit.

## 17. Update auf TrueNAS SCALE

1. **Backup** (siehe 18.).
2. **Branch pushen.** Die CI baut das Image `ghcr.io/icebrezzer/kickbase-insights:codex-autotrader-2` (oder `:sha-<commit>`). Warte, bis der Lauf grün ist.
3. **Image tauschen:** In TrueNAS unter Apps → Kickbase Insights → Edit das Image-Tag auf `codex-autotrader-2` setzen. Volume `/data` und `.env` bleiben.
4. **Optional:** In der `.env` `KBI_AUTOMATION__TRADER_ADMINS=<dein Kickbase-Name>` setzen, um Gelerntes importieren oder zurücksetzen zu können.
5. **Starten.** Beim Start legt die App die neue Tabelle und Spalte an; im Log steht „Adding column shadowtrade.user_id“.
6. **Prüfen:** Automatik-Seite öffnen. „Autotrader jetzt“ erscheint nach der ersten Runde, spätestens nach 5 Minuten. **Live handeln bleibt aus**, bis du es bewusst einschaltest.

## 18. Backup und Rollback

- **Backup (SQLite):** App stoppen und den Ordner des `/data`-Volumes kopieren (`kickbase.db` samt `-wal`/`-shm` und `secret.key`). Bei laufender App: `sqlite3 kickbase.db ".backup backup.db"`.
- **Backup (PostgreSQL):** `pg_dump`.
- **Rollback:** App stoppen, Image-Tag zurück auf das vorige setzen. Die Datenbank kann bleiben: Alle Änderungen sind additiv, ältere Versionen ignorieren die neue Tabelle und Spalte. Wer ganz sicher gehen will, spielt das Backup zurück.
- **Lernwerte zurück:** `POST /api/automation/trader/reset?scope=global|league` (Admin). Alte Werte stehen im Ereignis `trader-import` und lassen sich per Import wiederherstellen.

## 19. Git

Branch `codex/autotrader-2`, **nicht gepusht**. Je Meilenstein Backend, Frontend und Doku getrennt:
- **Gesicherte Vorarbeit:** `ee6b633` Aufstellungsprüfung · `62e7efd` Kredit, Kaderaufbau, Debug · `e881f89` Layout · `c18537b` Doku.
- **Meilenstein 1:** `1b24457` · `0e72cb8` · `c4cfd04`.
- **Meilenstein 2:** `14c4216` · `07bb13f` · `528acb7`.
- **Meilenstein 3:** `a4a063c` · `78f6d28` · `3c0a553`.
- **Meilenstein 4:** `23a692e` · `1ea6ebb` · `2e2c62f`.
- **Meilenstein 5:** `e204d62` · `a727702` · `128fc5b`.
- **Meilenstein 6:** Audit-Korrekturen, Migrationstest, CI, Bericht.

## 20. Status je Arbeitspaket und Release-Empfehlung

| AP | Thema | Status |
|---|---|---|
| 0 | Bestandsaufnahme / API-Verifikation | Bestandsaufnahme getestet. API-Verifikation **blockiert** (kein Live-Zugang, keine Doku) – fail-closed abgesichert |
| 1 | Netto-Gewinn, Gebote | Getestet |
| 2 | Budget, Kredit, Portfolio | Getestet |
| 3 | Kaderplanung, sichere Verkäufe | Getestet |
| 4 | Deadline-Phasen, Rettung | Getestet. Kombinatorische Rettung bewusst nicht umgesetzt (gierige Auswahl mit Rücknahme, 1 Verkauf pro Runde) |
| 5 | Startelf 2.0 | Getestet. Gewichtung nicht kalibriert |
| 6 | Prioritäten, gemeinsame Optimierung | Getestet. Kein Ganzzahl-Löser (begründet in 9.) |
| 7 | Verkaufssystem, Stop-Loss | Getestet |
| 8 | Learning Engine 2.0 | Getestet |
| 9 | Schattentransfers | Getestet |
| 10 | Risk Engine | Getestet |
| 11 | Transaktionen, Parallelität, Datenfrische | Getestet. Rundensperre mehrerer Container offen (14.) |
| 12 | Validierung, Rechte, Notabschaltung | Getestet |
| 13 | Probelauf, Statistik | Getestet |
| 14 | Backtesting | Getestet (nur Gewinnhandel, begründet) |
| 15 | Strategieprofile | Implementiert. Kalibrierung offen |
| 16 | Frontend, Transparenz, Benachrichtigungen | Getestet (Demo, Browser) |
| 17 | Performance | Gemessen (Demo). Last mit vielen Ligen offen |
| 18 | Automatisierte Tests | Getestet (s. 10.). `check_locks` unter Windows vorbestehend rot |
| 19 | Dokumentation | Abgenommen von mir; deine Abnahme steht aus |
| 20 | 360°-Audit | Durchgeführt. Funde 16–18 behoben |

**Release-Empfehlung:** Für den **Probelauf** in deiner Liga freigegeben. Für **Live-Handel** noch nicht, erst wenn:
1. der CI-Lauf mit Docker-Image grün ist,
2. der Probelauf mindestens zwei Spieltage lang plausible Entscheidungen zeigt (Dashboard „Warum gekauft oder nicht“, Debug-Export),
3. der Backtest deiner Liga das gewählte Profil gegenüber „Kein Handel“ und der alten Regel bestätigt,
4. du Live **bewusst** einschaltest, am besten zuerst mit dem Profil Konservativ.
