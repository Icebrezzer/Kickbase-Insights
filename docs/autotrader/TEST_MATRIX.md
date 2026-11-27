# Testmatrix

Legende: ✅ vorhanden und grün (27.11.2026 lokal) · 🟡 teilweise · ⬜ geplant (Paket) · ❌ nicht ausgeführt

## 1. Bestehende Suites

| Skript | Inhalt | CI | Lokal 27.11. |
|---|---|---|---|
| `check_coach.py` | Manager-Formeln, Elf, Prognose | ja | ✅ |
| `check_trader.py` | Grundentscheidungen | ja | ✅ |
| `check_trader_safety.py` | Netto-Gewinn, Risk Engine, Kredit, Phasen, Invarianten | ja | ✅ 969 |
| `check_trader_intelligence.py` | Elf, Prioritäten, Exits | ja | ✅ 29 |
| `check_trader_learning.py` | Gewinnchance, Liga-Modelle, Prognosepause | ja | ✅ 53 |
| `check_trader_backtest.py` | kein Look-ahead, echte Gewinnerpreise | ja | ✅ 19 |
| `check_audit_regressions.py` | Audit-Befunde 1–39 | ja | ✅ |
| `check_league_preferences.py` | Isolation, Migration, Grenzen | ja | ✅ |
| `check_wealth.py` | Vermögensrekonstruktion | ja | ✅ |
| `check_locks.py`, `check_leader.py` | Prozesssperren, Leader | ja | ✅ |
| `smoke_manager_tools.py` | Demo-Integration inkl. Live-Pfad mit Mock | ja | ✅ nach Fix KI-19 |
| `check_trader_migration.py <alt>` | DB eines Alt-Release öffnen | **nein** (E11.06) | ✅ gegen `ebf50d3` |
| `benchmark_audit.py` | Performance-Kurztest | nein | ❌ nicht ausgeführt |
| `tools/autotrader/check_analyze_export.py` | Export-Analyse | ja (ab E00) | ✅ |
| Frontend `npm run build`, `npm test` | TS, Vite, 5 Unit-Tests | ja | ❌ kein Node lokal (CI ✅ für `4b85715`) |
| ui-audit (Playwright Chromium + WebKit) | Screenshots, Overflow, Sitzungsregressionen | ja | ❌ |

## 2. Pflichtszenarien Auto-Trader 3.0 (Übergabe §25) → Paket

### Finanzierung
| Szenario | Paket | Status |
|---|---|---|
| Spieltag in 6 Tagen / 24 h / < 1 h / unbekannte Deadline | E04.02 | ⬜ (2.0-Phasen: ✅ in safety) |
| Voll ausgeschöpftes Maximalgebot | E04.06 | ⬜ |
| Negativer Kontostand | E04.08 | 🟡 Rettung 2.0 ✅ |
| Mehrere gleichzeitig gewonnene Auktionen | E04.06 | 🟡 Worst Case 2.0 ✅ |
| Verlorene Auktionen | E04.04/05 | ⬜ |
| Verbrauchte Verkaufslimits | E04.02 | 🟡 Kredit mit `sales_left` ✅ |
| Gesperrte Spieler, Sperrenablauf | E04.02 | ⬜ |
| Sinkende Marktwerte, schlechtere Erlöse | E04.03 | ⬜ |
| Doppelt beanspruchte Erlöse | E04.06, E04.10 | ⬜ |
| Bedingte Startelf-Transfers | E04.05 | ⬜ |
| Gewinnspieler als Tilgung | E04.04 | ⬜ |
| Ausfall der Kickbase-API, verzögerte Verkäufe | E04.09 | 🟡 Pause/Abgleich 2.0 ✅ |
| Neustart während der Tilgung | E04.05/09 | ⬜ |

### Schattentransfers
| Szenario | Paket | Status |
|---|---|---|
| Gewonnene/verlorene hypothetische Auktionen, Gleichstand, fehlender Gewinnerpreis | E03.04 | 🟡 2.0 ✅ (eine Variante) |
| Doppelte Beobachtungen, mehrere Varianten je Auktion | E03.01, E03.04 | ⬜ |
| Unvollständige Marktwerthistorien | E03.05 | ⬜ |
| Verschiedene Haltedauern | E03.05 | ⬜ |
| Fehlende Finanzierung, Kader-/Vereinslimit | E03.02 | ⬜ |
| Kein Zukunftswissen | E03.05 | 🟡 Backtest ✅ |
| Unabhängige virtuelle Konten | E09.01 | ⬜ |
| Keine Live-API-Schreibzugriffe (Zähl-Mock) | E03.01 | ⬜ |

### Konfiguration
| Szenario | Paket | Status |
|---|---|---|
| Ungültige Werte, unbekannte Parameter | E02.02 | 🟡 Klemmen/`ignored` 2.0 ✅ |
| Alte Versionen, Migration | E02.02, E02.03 | ⬜ |
| Gleichzeitige Änderungen | E02.05 | ⬜ |
| Rollback | E02.07 | ⬜ |
| Hot Reload, Änderung während einer Runde | E02.04 | ⬜ |
| Liga-Isolation | E02.03 | 🟡 2.0 ✅ |
| Deaktivierte Flags = altes Verhalten | E02.08 + jedes Flag-Paket | ⬜ |

### Lernsystem
| Szenario | Paket | Status |
|---|---|---|
| Zu geringe Stichprobe | E10.01 | 🟡 `MIN_SAMPLES` 2.0 |
| Zufällige kurzfristige Gewinne, Überanpassung | E10.02/03 | ⬜ |
| Verschlechterung, automatischer Rollback | E10.07 | ⬜ |
| Marktveränderungen, unterschiedliche Ligen | E10.02, E07.01 | 🟡 Liga-Modell 2.0 |
| Begrenzung der Lernparameter | E10.05 | 🟡 `LEARNED_LIMITS` 2.0 ✅ |

## 3. Regeln

- Jedes neue `check_*.py` wird im selben Commit in `.github/workflows/build.yml` eingetragen.
- Tests mit Datum/Uhrzeit verwenden feste Zeitpunkte oder werden aus den Phasenfunktionen abgeleitet (Lehre aus KI-19).
- Determinismus-Test für jedes Flag-Paket: Flag `off` → identische Aktionen wie vor dem Paket.
