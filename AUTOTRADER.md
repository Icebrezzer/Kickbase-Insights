# Autotrader – komplette Logik

Stand: 25.11.2026. Code: `backend/core/trader.py` (reine Entscheidungen), `backend/sync/trader.py` (Ablauf, Kickbase, Lernen, Protokoll), Aufruf aus `backend/sync/automation.py`. Geldbeträge in Euro.

---

## 0. Überblick

```
alle 5 Min. (KBI_AUTOMATION__INTERVAL_MINUTES) je Nutzer und Liga
└─ Automatik-Runde
   ├─ [1] Schalter prüfen
   ├─ [2] Daten holen
   ├─ [3] Alte Gebote abrechnen  ──► Lernen (Auktionen)
   ├─ [4] Schattentransfers abrechnen ──► Lernen (Gebot, Prognose, Marge, Tausch-Schwelle)
   ├─ [5] Planen
   │    ├─ 5.1 Spieler bewerten
   │    ├─ 5.2 Sperren (Startelf, frische Käufe)
   │    ├─ 5.3 Minus vor dem Spieltag ausgleichen  (beendet die Planung)
   │    ├─ 5.4 Gewinnkäufe mit gedrehter Prognose verkaufen
   │    ├─ 5.5 Offene Gebote prüfen, unnötige zurückziehen
   │    ├─ 5.6 Geld, Kredit, Kaderplätze
   │    ├─ 5.7 Kandidaten und Reihenfolge
   │    ├─ 5.8 Gebote (und höchstens ein Verkauf für Platz/Geld)
   │    └─ 5.9 Debug-Protokoll
   ├─ [6] Ausführen (Live) oder protokollieren (Probelauf)
   ├─ [7] Schattentransfers starten
   └─ [8] Push-Nachrichten senden
danach: automatische Aufstellung (eigene Funktion, nutzt neue Spieler schon in derselben Runde)
```

---

## 1. Schalter

| Schalter | Wo | Wirkung |
|---|---|---|
| `KBI_AUTOMATION__TRADER` | Server (.env) | `false` = Autotrader für alle aus |
| Autotrader | Automatik-Seite, je Liga | an/aus, Standard aus |
| Live handeln | je Liga | aus = Probelauf: nichts geht an Kickbase, Plan wird protokolliert (einmal pro Spieler, Art und Tag) |
| Gewinnhandel | je Liga | erlaubt Käufe nur wegen Marktwertgewinn |
| Schattentransfers | Feineinstellung `shadow` | Papiergeschäfte zum Lernen |
| `KBI_AUTOMATION__TRADER_ADMINS` | Server | wer gelernte Werte importieren darf (leer = jeder) |

Die Runde läuft unter einer Sperre je Nutzer/Liga, damit sich Trader und Aufstellung nicht überschneiden.

---

## 2. Daten je Runde

- Kader des Nutzers, Kontostand (`budget`), Transfermarkt (mit eigenen Geboten).
- Gespeicherte Aufstellung bei Kickbase (für die Startelf-Sperre).
- Aus der Datenbank: Spielplan/Deadline, Marktwertverläufe, erwartete Punkte, Form, Einsatzquote, Bieter-Modell der Liga (Gebotsspanne je Angebot), Kader- und Vereinslimit, eigene Trade-Historie (60 Tage), gelernter Zustand, gelernte Sofortverkaufs-Quote (sonst 0,9).

---

## 3. Gebote abrechnen (`_settle`)

Für jedes eigene Trader-Gebot mit Status `open`:

| Befund | Status | Lernen |
|---|---|---|
| Spieler noch auf dem Markt, aber kein eigenes Gebot mehr | `expired` (zurückgezogen) | – |
| Spieler jetzt im Kader | `won`, `paid` = Kaufpreis | `after_auction(gewonnen)` |
| Transfer an einen anderen Manager gefunden | `lost`, Gewinnerpreis gemerkt | `after_auction(verloren, Gewinnerpreis)` |
| Weg, kein Transfer, älter als 1 Tag | `expired` | – |
| sonst | bleibt `open` (Sync hat den Transfer noch nicht) | – |

---

## 4. Schattentransfers abrechnen (`_settle_shadows`)

Erledigte Schatten werden nach 120 Tagen gelöscht.

**Papier-Kauf** (`buy`):
1. *watching* – Spieler noch auf dem Markt → warten.
2. Transfer gefunden → gewonnen, wenn Gewinnerpreis ≤ Papiergebot → *holding*, sonst *lost*. Lernt `after_auction` mit halbem Gewicht.
3. Kickbase-Angebot ohne Käufer nach 1 Tag → als gewonnen gewertet (halbes Gewicht).
4. Nach 2 Tagen ohne Ergebnis → *expired*.
5. *holding* – nach 2 Marktwert-Updates (`PROFIT_HOLD`): Ergebnis = Wert danach × Verkaufsquote − Papierpreis → *done*. Lernt `after_forecast`; nur Zweck `profit` lernt zusätzlich `after_sale` (halbes Gewicht). Zweck `near` (von den Regeln abgelehnt) lernt die Marge nicht, sonst würde sie nur steigen.

**Papier-Verkauf** (`sell`, zu jedem echten Verkauf): nach 3 Updates (`REGRET_DAYS`) Ergebnis = Wert danach − Wert beim Verkauf → `after_regret`.

---

## 5. Planen (`_plan`)

### 5.1 Spieler bewerten (`Candidate`)

Für jeden eigenen und jeden Marktspieler:

| Feld | Bedeutung |
|---|---|
| `expected` | erwartete Punkte nächster Spieltag |
| `average` | Saisonschnitt |
| `form` | gewichtete Punkte der letzten bis zu 5 Einsätze |
| `play` | Anteil der letzten 5 Vereinsspiele mit Einsatz (unbekannt = `None`) |
| `fit` | Status gilt als einsatzfähig |
| `today` | Marktwertänderung des letzten Updates |
| `forecast` | Prognose nächstes Update |
| `gain` | Prognose über 2 Updates × gelerntes Prognose-Vertrauen |
| `value`, `price`, `bid_low`, `bid_high`, `expires_at` | Marktwert, Angebotspreis, Gebotsspanne, Auktionsende |

Regelmäßiger Spieler (`regular`): `play ≥ min_play`. Ohne Daten gilt ein Kaderspieler als Stammspieler (niemand wird wegen fehlender Zahlen verkauft); ein Marktziel ohne Daten gilt **nicht** als Stammspieler.

Beste Elf: `coach.best_eleven` über alle erlaubten Formationen nach erwarteten Punkten. Leere Plätze zählen intern mit Strafe 1000 Punkte.

### 5.2 Sperren (`locked` = wird nicht verkauft)

- **Startelf-Sperre** (`starters_locked`): von `starter_lock` Minuten (Std. 60) vor dem ersten Anpfiff eines Spieltags bis 5 Minuten danach. Beispiel Fr 20:30 → gesperrt 19:30–20:35, ab 20:35 wieder verkäuflich.
- Ohne automatische Aufstellung und außerhalb eines laufenden Spieltags bleibt die Startelf **immer** gesperrt (sonst entstünde eine Lücke, die niemand füllt).
- Startelf = gespeicherte Kickbase-Aufstellung, sonst die beste Elf.
- **Frische Trader-Käufe**: 20 Std. (`MIN_HOLD`) gesperrt, außer verletzt.

### 5.3 Minus vor dem Spieltag ausgleichen (Rettung)

- Rückzahlungsbeginn = letztes Marktwert-Update (22:00 Berlin) vor der Deadline + 15 Min., spätestens 1 Std. vor der Deadline. Beispiel Anpfiff Fr 20:30 → ab Do 22:15.
- Ist `budget < 0` und jetzt ≥ Rückzahlungsbeginn und < Deadline:
  - `coach.rescue_sales`: verkauft gierig die Spieler mit dem geringsten Punktverlust je Euro (Wert × Verkaufsquote), bis der Kontostand ≥ 0 ist; nimmt danach unnötige Verkäufe zurück. Gesperrte fitte Spieler sind geschützt.
  - Reicht das nicht: Ereignis + Push „Minus lässt sich nicht ganz ausgleichen“ (einmal je Spieltag).
  - Die Planung endet hier: nur Rettungsverkäufe, keine Gebote.
- Bei Serverausfall wird jede Runde (alle 5 Min.) bis zur Deadline erneut versucht.

### 5.4 Gewinnkäufe mit gedrehter Prognose verkaufen

Zwischen `sell_advice_hour` (Std. 20) und 22 Uhr, wenn noch Tagesverkäufe frei sind: **ein** Trader-Gewinnkauf, der nicht gesperrt, nicht in der besten Elf ist und dessen Prognose < 0 ist, wird verkauft (Zweck `turn`).

### 5.5 Offene Gebote als künftiger Kader

- Alle eigenen offenen Gebote zählen als Spieler, die noch kommen (`planned` = Kader + offene Gebote).
- Gebote, die der Nutzer selbst abgegeben hat: zählen mit, werden **nie** angefasst.
- Trader-Gebote werden neu geprüft, in dieser Reihenfolge: Startelf vor Ersatz vor Gewinnhandel, je höhere erwartete Punkte zuerst.
  - Startelf-Gebot: noch ein Upgrade gegenüber `planned`?
  - Ersatz-Gebot: fehlt der Position noch ein Ersatz?
  - Gewinnhandel: bleibt.
  - Nicht mehr nötig → **Gebot zurückziehen** (Aktion `withdraw`, „kein Bedarf mehr“).

### 5.6 Geld, Kredit, Kaderplätze

```
cash_free = Kontostand − Reserve − Summe offener Gebote + Erlöse geplanter Verkäufe
slots     = Kaderlimit − Kader − offene Gebote
max_bid   = 33-%-Regel: (Mannschaftswert + Kontostand) × 0,33 (+ Kontostand, wenn negativ)
repayable = Σ Marktwert × Verkaufsquote aller Spieler außerhalb der besten Elf
credit    = max(0, min(max_bid − max(Kontostand, 0), repayable − max(0, −Kontostand)))
```

- Geld für ein Gebot = `cash_free + credit`.
- **Ausnahme**: Auktionen, die zwischen Rückzahlungsbeginn und Deadline enden → nur `cash_free` (kein neues Minus kurz vor dem Anpfiff).
- Lücken-Reserve: solange die Elf Lücken hat, bleiben je **weitere** Lücke `cover_max_price` (Std. 3 Mio.) zurück.
- Anteil je Zweck: Startelf und Ersatz bis `lineup_share` (100 %), Gewinnhandel bis `profit_share` (60 %) dieses Geldes.

### 5.7 Kandidaten und Reihenfolge

Ausgeschlossen: eigenes Gebot offen, eigenes Angebot, in den letzten 7 Tagen verkauft (`REBUY_BLOCK`), Vereinslimit voll, keine Marktdaten.

Für jeden übrigen Marktspieler genau ein Zweck:

**a) Startelf (`lineup_upgrade` gegen `planned`)**
1. fit, `play` bekannt und ≥ `min_play` (Std. 60 %).
2. Er kommt in die neue beste Elf.
3. Füllt er eine Lücke (`fills`): reicht das. Sonst Punktgewinn ≥ `min_gain` (Std. 2,0).
4. Gewinn = echte erwartete Punkte (ohne Lücken-Strafe).
5. Verdrängt er jemanden (bevorzugt gleiche Position, sonst der schwächste Verdrängte):
   - Saisonschnitt > Verdrängter **und** ≥ Verdrängter × (1 + `min_avg_edge`) (Std. +10 %),
   - Form > Form des Verdrängten.
6. Rang: Lücke füllen 2·10⁹ + Gewinn, Verbesserung 10⁹ + Gewinn.

**b) Gewinnhandel** (nur wenn kein Startelf-Upgrade, Gewinnhandel an, nicht pausiert): fit und Prognose > 0. Rang = Marge beim Mindestgebot.

**c) Ersatz** (`cover_target`, nur Spieler ohne Startelf-Zweck): Position ohne fitten Ersatz über die beste Elf hinaus; Kandidat fit, `play` ≥ `min_play`/2, Prognose ≥ 0, Preis ≤ `cover_max_price`. Rang: −10⁹ − Preis (billigster zuerst).

Ergebnis: **Lücken füllen → Elf verbessern → Gewinnhandel → Ersatzbank.**

**Stop-Loss**: realisierter Verlust der Woche > `stop_loss` (Std. 3 Mio.) → Gewinnhandel pausiert bis zur nächsten ISO-Woche.

### 5.8 Gebote

Für jeden Kandidaten in Rangfolge (jeder Spieler nur einmal):

1. Gewinnhandel: Schattenkauf vormerken (max. 5 je Runde) zum realistischen Gebot; `profit`, wenn die Regeln ihn kaufen würden, sonst `near`.
2. Tageslimit `daily_bids` (Std. 6) erreicht → überspringen.
3. Bedarf neu prüfen (jedes Gebot dieser Runde zählt sofort zu `planned`):
   - Startelf: Upgrade noch gültig? Sonst „Platz schon besetzt“.
   - Gewinnhandel/Ersatz: hat die Elf noch Lücken → „erst die Startelf füllen“. Ersatz-Position schon gedeckt → überspringen.
4. **Preis** (`_price` → `bid_for`):
   ```
   low  = max(bid_low, Angebotspreis, Marktwert)
   high = max(bid_high, low)
   bid  = low + extra[Preisklasse] × (high − low)        extra gelernt, 0..1
   Gewinnhandel: bid ≤ Marktwert + gain/2               (halber Gewinn bleibt)
   aufrunden auf 10.000 €
   ungültig, wenn bid > Obergrenze (Geld × Anteil; Ersatz zusätzlich ≤ cover_max_price)
   ```
   - Preisklassen: < 5 Mio. / 5–15 Mio. / ≥ 15 Mio.
   - `bid_low`/`bid_high` kommen aus dem Bieter-Modell der Liga (übliche Aufschläge, wahrscheinliche Mitbieter, deren Max-Gebote).
   - Gewinnhandel: Marge = gain − (bid − Marktwert) muss ≥ gelernte `min_margin` sein, Prognose > 0, heute ≥ 0, fit.
   - Startelf: Preis je Punkt = max(bid − Marktwert des Verdrängten, 0) / Punktgewinn ≤ `max_cost_per_point` (Std. 300.000 €). Sonst Versuch mit dem niedrigsten Gebot (`extra` = 0); passt auch das nicht → kein Gebot.
5. Kein gültiger Preis oder kein Platz → **höchstens ein Verkauf je Runde**, nur wenn:
   - nicht Ersatz, noch Tagesverkäufe (`daily_sales`, Std. 3), in dieser Runde noch nichts verkauft,
   - Auktion endet in ≤ `sell_window` Minuten (Std. 20),
   - `pick_sale` findet jemanden (nie gesperrt, nie die Ziel-Person, Ersatz je Position bleibt erhalten):
     1. bei Startelf zuerst der Verdrängte,
     2. sonst in Verkaufsreihenfolge: verletzt → kein Stammspieler → Bank nach schwächstem Tagesanstieg,
     3. nie ein fitter Spieler der besten Elf; ein Bankspieler nur, wenn das Ziel um ≥ `swap_edge` (gelernt) mehr pro Tag steigen soll und heute nicht schwächer ist.
   - Dann Gebot mit mindestens 0,6 der Spanne (`ROOM_EXTRA`) und Geld inkl. Verkaufserlös. Passt es nicht → kein Verkauf, kein Gebot.
6. Gebot geplant → Geld, Plätze, Tageslimit verringern, Spieler zu `planned`.

### 5.9 Debug-Protokoll (`TraderDebug`)

Je Runde, nur wenn sich Aktionen oder Begründungen geändert haben (21 Tage aufbewahrt):

- Kontostand, `cash_free`, Kredit, Reserve, offene Gebote, Plätze, Restlimits, Pause, Startelf-Sperre, Verkaufsquote, Deadline, Rückzahlungsbeginn.
- Kader und offene Gebote mit allen Kennzahlen.
- Jeder Marktspieler mit Kennzahlen, verfügbarem Geld und `decision` (Begründung).
- Übersprungene Spieler mit Grund, geplante Aktionen.
- Rettungsrunden mit Kontostand danach.

---

## 6. Ausführen

| Aktion | Live | Probelauf |
|---|---|---|
| Gebot | `place_offer`, TradeLog `open`, Ereignis + Push | TradeLog `planned`, Ereignis (1× je Spieler/Tag) |
| Verkauf | Sofortverkauf an Kickbase (unwiderruflich), TradeLog `sold` mit Gewinn (gegen Kaufpreis), Ereignis + Push | wie Gebot |
| Gebot zurückziehen | Angebots-ID vom Markt holen, `withdraw_offer` | nur Ereignis |

- Fehler bei Kickbase → Ereignis „fehlgeschlagen“, Rest der Runde wartet (der Plan setzte den Schritt voraus).
- Abgemeldete Sitzung → Abbruch, die Automatik meldet „Bitte neu anmelden“.
- Verkauf eines Trader-Gewinnkaufs → lernt `after_sale` (und `after_forecast`).

---

## 7. Lernen (gemeinsam für alle Ligen, `ModelState "trader"`)

| Wert | Start | Grenzen | Regel |
|---|---|---|---|
| `extra[Klasse]` | 0,3 | 0–1 | gewonnen −0,05·w, an höheres Gebot verloren +0,15·w (w = 1 echt, 0,5 Schatten) |
| `min_margin` | 150.000 | 50.000–1,5 Mio. | Gewinnverkauf mit Verlust ×(1+0,15w), mit Gewinn ×(1−0,03w) |
| `gain_ratio` | 1,0 | −1…2 | gleitend 0,9·alt + 0,1·(tatsächlich/Prognose); Prognosen < 50.000 zählen nicht |
| Prognose-Vertrauen | 1,0 | 0,3–1,2 | = `gain_ratio`, erst ab 10 Verläufen |
| `swap_edge` | 100.000 | 50.000–1 Mio. | Verkaufter stieg danach > 100.000 → ×1,1, sonst ×0,97 |
| Zähler | 0 | ≥ 0 | won, lost, shadow_won, shadow_lost, gain_samples, regret_samples |

---

## 8. Statistik

Wochenweise (ISO-Woche): Probelauf-Einträge, Gebote, gewonnen/verloren, Verkäufe, Ausgaben, Erlöse, realisierter Gewinn, Punktgewinn der Startelf-Käufe, Anzahl und Ergebnis der Schattentransfers. Dazu Trefferquote und „nach Verkauf gestiegen“ der Schattentransfers.

---

## 9. Einstellungen je Liga (Feineinstellungen)

| Schlüssel | Standard | Grenzen | Bedeutung |
|---|---|---|---|
| `min_gain` | 2,0 | 0–100 | Mindest-Punktgewinn der Elf |
| `max_cost_per_point` | 300.000 | 0–50 Mio. | Aufpreis je gewonnenem Punkt |
| `min_avg_edge` | 10 % | 0–200 | Schnitt über dem Verdrängten |
| `min_play` | 60 % | 0–100 | Einsatzquote |
| `lineup_share` | 100 % | 10–100 | Geldanteil Startelf/Ersatz |
| `profit_share` | 60 % | 10–100 | Geldanteil Gewinnhandel |
| `reserve` | 0 | 0–500 Mio. | nie ausgegeben |
| `cover_max_price` | 3 Mio. | 0–50 Mio. | Ersatz höchstens; auch Reserve je Lücke |
| `daily_bids` | 6 | 0–30 | Gebote pro Tag |
| `daily_sales` | 3 | 0–30 | Verkäufe pro Tag |
| `stop_loss` | 3 Mio. | 0–100 Mio. | Wochenverlust, ab dem der Gewinnhandel pausiert |
| `sell_window` | 20 Min. | 5–180 | Verkauf für Platz nur so kurz vor Auktionsende |
| `starter_lock` | 60 Min. | 0–1440 | Startelf-Sperre vor dem ersten Anpfiff |
| `shadow` | an | – | Schattentransfers |

Feste Regeln (nur per neuem Build änderbar): Haltedauer Prognose 2 Updates, Rückkaufsperre 7 Tage, Mindesthaltezeit 20 Std., 5 Min. nach Anpfiff, `ROOM_EXTRA` 0,6, Lernschwelle 10, Schatten-Gewicht 0,5, Lücken-Strafe 1000, Preisklassen, Gebotsschritt 10.000 €, Verkaufsquote ohne Daten 0,9, 5 Schatten je Runde.

---

## 10. Export und Import

- **Export** (`GET /api/automation/trader/export?days=1–60`, Knopf auf der Automatik-Seite): Erklärtext, Schalter, Einstellungen mit Grenzen, gelernte Werte mit Grenzen, feste Regeln, Trades, Schattentransfers, Ereignisse, Debug-Runden.
- **Import** (`POST /api/automation/trader/import`): `{"options": {...}, "learned": {...}}`. Nur genannte Schlüssel ändern sich, alles wird begrenzt, unbekannte Schlüssel werden gemeldet. `options` gilt für die Liga, `learned` für alle Ligen (nur `KBI_AUTOMATION__TRADER_ADMINS`).

---

## 11. Schutzmechanismen (Zusammenfassung)

1. Server-Schalter, Liga-Schalter, Probelauf als Standard, Rückfrage vor „Live handeln“.
2. Offene Gebote zählen als ausgegeben **und** als künftige Spieler; überflüssige Trader-Gebote werden zurückgezogen.
3. Kredit nur bis zum Max-Gebot und nur so weit, wie die Bank ihn zurückzahlt; kein Kredit für Auktionen kurz vor dem Spieltag.
4. Rückzahlung ab dem Vorabend, Push wenn nicht ausgleichbar.
5. Elf zuerst, Geld für die übrigen Lücken reserviert.
6. Preis-Leistung je Punkt, Mindestgewinn, Mindestmarge (gelernt), halber Prognosegewinn bleibt immer.
7. Höchstens ein Verkauf je Runde, nur kurz vor der Auktion, für die er Platz schafft; nie die beste Elf, immer ein Ersatz je Position.
8. Startelf-Sperre um den Anpfiff, Mindesthaltezeit, Rückkaufsperre.
9. Tageslimits, Wochen-Stop-Loss, Reserve.
10. Alle gespeicherten und importierten Werte werden geprüft und begrenzt.

## 12. Bekannte Grenzen

- Kickbase-Antworten zu Aufstellung, Sofortverkaufspreis und Zurückziehen sind undokumentiert; Zurückziehen ist nicht gegen Kickbase getestet.
- Fällt der Server von Vorabend bis Deadline durchgehend aus, bleibt ein Minus stehen.
- Pro Lücke wird nur einmal geboten; bei verlorener Auktion folgt das nächste Gebot frühestens in der nächsten Runde.
- Das Lernen ist für alle Nutzer des Servers gemeinsam.
