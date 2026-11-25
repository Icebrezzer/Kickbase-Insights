# Autotrader – komplette Logik

Stand: 25.11.2026, Branch `codex/autotrader-2`, Meilensteine 1 (Critical Safety Patch), 2 (Trading Intelligence) und 3 (Learning Engine 2.0).

Code:
- `backend/core/trader.py`: reine Entscheidungen (Bewertung, Preis, Netto-Gewinn, Kredit, Phasen, Lernen).
- `backend/core/risk.py`: Risk Engine, prüft jede geplante Aktion unabhängig von der Strategie.
- `backend/sync/trader.py`: Ablauf, Kickbase-Aufrufe, Transaktionsstatus, Lernen, Protokoll.
- Aufruf aus `backend/sync/automation.py`.

Alle Geldbeträge sind in Euro.

Leitlinie: **Sicherheit vor Rendite. Bestätigte Daten vor Annahmen. Nettoertrag vor Marktwertgewinn.**

---

## 0. Überblick

```
alle 5 Min. (KBI_AUTOMATION__INTERVAL_MINUTES) je Nutzer und Liga, unter einer Sperre je Nutzer/Liga
└─ Runde
   ├─ [1] Schalter prüfen (Server, Liga)
   ├─ [2] Daten holen (Kader, Kontostand, Markt, gespeicherte Aufstellung)
   ├─ [3] Abrechnen: unklare Aufrufe mit Kickbase abgleichen, offene Gebote → gewonnen/verloren
   ├─ [4] Schattentransfers abrechnen (lernt nur, wenn Schattentransfers an)
   ├─ [5] Planen (Strategie)
   │    ├─ Phase bestimmen (normal / prepare / repay / final)
   │    ├─ repay/final: Kontostand zum Spieltag sichern (Gebote zurückziehen, Rettungsverkäufe)
   │    ├─ Gewinnpositionen: halten oder verkaufen (Ausstiegssystem, 5.10)
   │    ├─ unnötige eigene Gebote zurückziehen
   │    ├─ Geld, Kredit, Gewinnhandels-Rahmen
   │    ├─ Kandidaten, Reihenfolge, Preise
   │    └─ höchstens ein Verkauf für Platz
   ├─ [6] Risk Engine: jede Aktion prüfen, unzulässige blockieren (Reason-Code)
   ├─ [7] Debug-Protokoll (nur bei Änderung)
   ├─ [8] Ausführen (Live) – nach jedem Verkauf und jedem unbestätigten Schritt endet die Runde
   │      oder protokollieren (Probelauf / automatische Pause)
   ├─ [9] Schattenverkäufe nur zu bestätigten Verkäufen
   └─ [10] Push-Nachrichten (Fehler beim Push ändern nie ein Handelsergebnis)
danach: automatische Aufstellung
```

---

## 1. Schalter

| Schalter | Wo | Wirkung |
|---|---|---|
| `KBI_AUTOMATION__TRADER` | Server | `false` = Autotrader für alle aus |
| Autotrader | Automatik-Seite, je Liga | Standard aus |
| Live handeln | je Liga | Standard aus. Aus = Probelauf: nichts geht an Kickbase. Einschalten nur mit Rückfrage |
| Gewinnhandel | je Liga | Käufe nur wegen Marktwertgewinn |
| Schattentransfers | Option `shadow` | aus: keine neuen Schatten, offene werden nur noch statistisch abgeschlossen, nichts gelernt |
| Notfallregel | Option `rescue_override` | Standard aus. An: Rettungsverkäufe dürfen gesperrte Spieler verkaufen (Rückfrage) |
| `KBI_AUTOMATION__TRADER_ADMINS` | Server | wer gelernte Werte (alle Ligen) importieren darf. **Leer = niemand** |

- Vor **jeder** Live-Aktion werden Server-, Liga- und Live-Schalter neu gelesen. Wer mitten in der Runde ausschaltet, stoppt alle weiteren Aktionen.
- **Automatische Pause:** Bei 3 fehlgeschlagenen Kickbase-Aufrufen innerhalb einer Stunde läuft der Trader bis zum Abklingen nur als Probelauf. Das wird protokolliert, per Push gemeldet und auf der Seite angezeigt.

---

## 2. Daten

- **Live von Kickbase:** Kader, Kontostand, Transfermarkt inkl. eigener Gebote, gespeicherte Aufstellung.
- **Gespeicherte Aufstellung nicht lesbar:** Es wird nicht die rechnerisch beste Elf angenommen. Während der Startelf-Sperre gilt jeder fitte Spieler als gesperrt.
- **Aus der Datenbank:** Spielplan und Deadline, Marktwertverläufe, erwartete Punkte, Form, Einsatzquote, Bieter-Modell, Kader- und Vereinslimit, Trade-Historie (60 Tage), gelernter Zustand.
- **Verkaufsquote, konservativ:** `min(gelernt, 0,9)`. Ohne gelernte Quote gilt 0,9. Ein gelernter höherer Wert wird nie verwendet.

---

## 3. Abrechnen (`_settle`)

### 3.1 Unklare Aufrufe (`pending`, `unknown`)

| Befund bei Kickbase | Ergebnis |
|---|---|
| Gebot: eigenes Gebot sichtbar oder Spieler im Kader | `open` (danach normal abgerechnet) |
| Verkauf: Spieler nicht mehr im Kader | `sold`, Erlös **unbekannt** (`received_known = false`), kein Gewinn |
| nach 10 Min. nichts davon | `failed` |

Ein Spieler mit unklarem Aufruf ist für neue Aktionen gesperrt (`BLOCKED`). Nichts wird blind wiederholt.

### 3.2 Offene Gebote

| Befund | Status | Lernen |
|---|---|---|
| Spieler noch auf dem Markt, kein eigenes Gebot mehr | `expired` | – |
| Spieler im Kader | `won`, `paid` = Kaufpreis | `after_auction(gewonnen)` |
| Transfer an anderen Manager | `lost` + Gewinnerpreis | `after_auction(verloren)` |
| weg ohne Transfer, > 1 Tag | `expired` | – |

---

## 4. Schattentransfers (`_settle_shadows`)

Erledigte Schatten werden nach 120 Tagen gelöscht.

**Auswahl:** bis zu 5 je Runde, zuerst der beste Kandidat **jeder Preisklasse**, dann die nächstbesten. So lernt der Trader nicht nur aus teuren Spitzenkandidaten. Abgelehnte Kandidaten werden als `near` mitbeobachtet.

**Papier-Kauf:**
- Ist ein Transfer bekannt: gewonnen, wenn der Gewinnerpreis **kleiner** als das Papiergebot war. Gelernt wird mit halbem Gewicht, im globalen Modell und in der Liga.
- **Gleichstand:** gilt als verloren, ohne Lerneffekt (wer den Zuschlag bekommt, ist unbekannt).
- **Ohne Transfer verschwunden** (kein Käufer, zurückgezogen, neu eingestellt): nach 2 Tagen `expired`, **kein** Lerneffekt, kein angenommener Sieg.
- Nach 2 Marktwert-Updates: Ergebnis = Wert × konservative Quote − Papierpreis.
- Gelernt wird `after_forecast` mit halbem Gewicht. Nur Zweck `profit` lernt zusätzlich `after_sale`.

**Papier-Verkauf:**
- Entsteht nur zu einem **bestätigten** echten Verkauf (nicht im Probelauf, nicht bei Fehlschlag).
- Nach 3 Updates: Was Halten netto mehr gebracht hätte = (Wert danach − Wert beim Verkauf) × Quote → `after_regret`.
- **Rettungsverkäufe lernen nichts:** Ein erzwungener Verkauf sagt nichts über die Tausch-Schwelle.

---

## 5. Planung

### 5.1 Bewertung (`Candidate`)

| Feld | Bedeutung |
|---|---|
| `expected` | erwartete Punkte am nächsten Spieltag |
| `average` | Saisonschnitt |
| `form` | Form aus den letzten bis zu 5 Einsätzen |
| `play` | Einsatzquote der letzten 5 Vereinsspiele, `None` = unbekannt |
| `fit` | einsatzfähig |
| `today` | Marktwertänderung am letzten Update |
| `forecast` | Prognose für das nächste Update |
| `gain` | Prognose über 2 Updates × Prognose-Vertrauen (konservativ, höchstens 1,0) |
| `ahead` | Ø erwartete Punkte der nächsten 3 Vereinsspiele, mit demselben Modell gerechnet: Quoten für den nächsten Spieltag, sonst Tabelle und Heim/Auswärts. `None` ohne Spielplan |
| `samples` | gespielte Spiele der letzten 5 Vereinsspiele (Datenmenge hinter Form und Einsatzquote) |
| `value`, `price`, `bid_low`, `bid_high`, `expires_at` | Marktwert, Preis, Gebotsspanne, Auktionsende |

Qualität: `0,6 × Saisonschnitt + 0,4 × Form`. Ist nur einer der Werte bekannt, gilt dieser. Ohne beide Werte gilt die Qualität als unbekannt. Die Gewichtung ist noch nicht durch ein Backtesting kalibriert (Meilenstein 4).

Nicht verfügbar und deshalb **nicht** verwendet:
- Startelf-Wahrscheinlichkeit getrennt von der Einsatzquote.
- Spielminuten.
- Konkurrenz auf der Position.
- Dauer von Verletzungen.

- Kaderspieler ohne Einsatzdaten gelten als Stammspieler. Niemand wird wegen fehlender Zahlen verkauft.
- Marktziele ohne Daten gelten **nicht** als Stammspieler.

### 5.2 Sperren (`locked`)

- **Startelf:** von `starter_lock` Min. (Std. 60) vor dem ersten Anpfiff bis 5 Min. danach. Ohne automatische Aufstellung und außerhalb des Spieltags immer.
- **Frische Trader-Käufe:** 20 Std. gesperrt, außer verletzt.

### 5.3 Phasen (`phase`, zustandslos aus Uhr und Deadline – auch nach einem Neustart)

| Phase | Zeitraum | Regeln |
|---|---|---|
| `normal` | sonst | Kredit nach `credit_mode` |
| `prepare` | ≤ 24 Std. vor Deadline | kein Kredit für Gewinnhandel |
| `repay` | ab letztem Marktwert-Update vor der Deadline (22:15 Berlin), spätestens 1 Std. vorher | Kontostand sichern (5.4). Kein Kredit für Auktionen, die vor der Deadline enden. Gewinn-Gebote nur auf Auktionen, die nach der Deadline enden |
| `final` | letzte 60 Min. | keine neuen Gewinn-Gebote, kein Kredit |

### 5.4 Kontostand zum Spieltag sichern (`repay`/`final`)

1. **Worst Case** = Kontostand − alle offenen Gebote (auch manuelle), deren Auktion vor der Deadline endet (oder Ende unbekannt).
2. Worst Case < 0: Die **eigenen Trader-Gebote** werden zurückgezogen, zuerst Gewinnhandel, dann Ersatz, dann Startelf, bis der Worst Case ≥ 0 ist. Manuelle Gebote bleiben stehen.
3. Kontostand < 0: Rettungsverkäufe planen (`coach.rescue_sales`, geringster Punktverlust je Euro, unnötige Verkäufe werden zurückgenommen). Gesperrte fitte Spieler sind geschützt, außer bei aktiver Notfallregel.
4. Lässt sich das nicht vollständig ausgleichen: Push „Minus nicht ganz ausgleichbar“ (einmal je Spieltag).
5. Pro Runde wird **ein** Verkauf ausgeführt. Die nächste Runde plant mit dem von Kickbase bestätigten Kontostand neu und hört auf, sobald er ≥ 0 ist.

### 5.5 Offene Gebote, Kaderzustände

- **Bestätigter Kader** (`own`): Grundlage für Verkäufe, Ersatzabsicherung und Kredit.
- **Prognostizierter Kader** (`planned`): bestätigter Kader + offene Gebote. Dient nur der Bedarfsermittlung, damit eine Position nicht doppelt gekauft wird.
- Trader-Gebote ohne Bedarf werden zurückgezogen (Startelf vor Ersatz vor Gewinnhandel behalten). Manuelle Gebote werden nie angefasst (`MANUAL_BID`).

### 5.6 Geld, Kredit, Gewinnhandels-Rahmen

```
free       = Kontostand − Reserve − alle offenen Gebote          (geplante Verkäufe zählen NICHT)
max_bid    = (Mannschaftswert + Kontostand) × 0,33 (+ Kontostand, wenn negativ)    [Kickbase-Regel, nicht verifiziert]
liquidation = simulierter Verkauf Spieler für Spieler in Verkaufsreihenfolge:
              nie gesperrt, nie beste Elf, nie letzter fitter Ersatz einer Position,
              höchstens daily_sales Verkäufe, Wert = (Marktwert + fallende Prognose) × konservative Quote
credit     = max(0, min(max_bid − max(Kontostand, 0), liquidation − max(0, −Kontostand)))
Kredit je Gebot: credit_mode 0 = nie, 1 = Startelf/Ersatz (Standard), 2 = auch Gewinnhandel; plus Phasenregeln
profit_room = profit_share % × (Mannschaftswert + Kontostand) − Gewinnbestände − offene Gewinn-Gebote
```

### 5.7 Kandidaten und Reihenfolge

Ausgeschlossen werden:
- Spieler mit eigenem Gebot oder unklarem Aufruf.
- Eigene Angebote.
- Spieler, die in den letzten 7 Tagen verkauft wurden.
- Spieler aus einem Verein, dessen Limit voll ist.
- Abgelaufene Auktionen.
- Spieler ohne Marktdaten.

| Zweck | Bedingungen | Bewertung innerhalb der Stufe |
|---|---|---|
| Lücke füllen | fit, Einsatzquote bekannt und ≥ `min_play`. Kein Mindestgewinn. Preis je Punkt aus echten Punkten | Punkte |
| Elf verbessern | zusätzlich: Gewinn ≥ `min_gain` (×1,5 bei weniger als 3 der letzten 5 Spiele). Qualität > Verdrängter × (1 + `min_avg_edge`). Ziel ohne Schnitt und Form = kein Tausch. Über die nächsten 3 Spiele nicht schlechter als der Verdrängte | Punkte |
| Gewinnhandel | kein Upgrade, Gewinnhandel an, kein Stop-Loss, fit, Prognose > 0, Auktionsende bekannt, nicht `final` | **Netto-Rendite je Euro und Update** beim Mindestgebot |
| Ersatz | fehlender fitter Ersatz einer Position, billigster zuerst, Preis ≤ `cover_max_price` | niedrigerer Preis |

**Dynamische Prioritäten** (`priority`), höchste Stufe zuerst:

| Phase | Reihenfolge |
|---|---|
| `normal` | Lücke → Verbesserung → Gewinnhandel → Ersatz |
| `prepare`, `repay`, `final` | Lücke → Ersatz → Verbesserung → Gewinnhandel |

- Solange die Elf (prognostiziert) Lücken hat, gibt es keine Gewinn- und keine Ersatz-Gebote.
- Ein Gewinn-Gebot lässt je fehlender Ersatzposition `cover_max_price` übrig. So verdrängt der Gewinnhandel die Ersatzbank nie dauerhaft.
- **Gemeinsame Planung:** Die Gebote werden in Prioritätsreihenfolge mit laufendem Budget, Kaderplätzen und Bedarf vergeben. Jedes Gebot verändert den prognostizierten Kader für die nächsten.
  - Gewinnhandel: Die Reihenfolge nach Rendite je Euro ist die gierige Lösung des Rucksackproblems. Sie ist bei teilbarem Budget optimal und bei wenigen Plätzen nahe am Optimum.
  - Startelf: Die Lücken-Reserve verteilt das Budget auf alle Lücken.
  - Auf einen Ganzzahl-Löser wurde bewusst verzichtet. Bei 6 Geboten pro Tag und ≤ 18 Plätzen brächte er laut Überschlag kaum Nutzen. Ein Backtest (Meilenstein 4) soll das bestätigen.
- **Stop-Loss:** Der Gewinnhandel pausiert, wenn eine der beiden Grenzen erreicht ist:
  - realisierter Wochenverlust der Gewinnpositionen ≥ `stop_loss`,
  - realisierter Verlust + Buchverlust der offenen Gewinnpositionen (Wert × Quote − Kaufpreis) ≥ `stop_loss`.

  Weitere Regeln:
  - Sporttransfers und Rettungsverkäufe zählen nicht. Probeläufe und unbekannte Erlöse ebenfalls nicht.
  - `0` = aus.
  - Woche = ISO-Woche in Berlin-Zeit. Wiederaufnahme mit der neuen Woche oder sobald der Buchverlust kleiner wird.
  - Die Rettung vor dem Spieltag läuft immer, auch bei aktivem Stop-Loss.

### 5.8 Netto-Gewinn und Preis

```
expected_proceeds = (Marktwert + gain) × konservative Verkaufsquote
expected_profit   = expected_proceeds − Gebot                     (Kickbase kennt keine Gebühr)
roi               = expected_profit / Gebot
max_profit_bid    = min(proceeds − min_margin, proceeds / (1 + min_roi)), abgerundet auf 10.000 €
Gewinnkauf nur wenn: fit, Prognose > 0, heute ≥ 0, profit ≥ min_margin (gelernt) UND profit ≥ Gebot × min_roi
```

Beispiel aus dem Auftrag:
- Annahmen: Marktwert 10 Mio., Prognose +800.000, Gebot 10,2 Mio., Quote 90 %.
- Erlös: 9,72 Mio.
- Ergebnis: **−480.000 €**, also kein Kauf. Auch die Risk Engine blockiert ihn (`PROFIT_NEGATIVE`).

**Gebot nach Erwartungswert (`best_bid`):** Das ist der Standard, sobald die Liga genug Auktionen hat.
- **Gewinnchance:** `P(win | Gebot)` = Anteil der gewonnenen Kickbase-Auktionen anderer Manager in der Liga (letzte 45 Tage, sonst alle), deren Gewinner **weniger** Aufschlag auf den Marktwert gezahlt hat.
  - Zuerst gilt die eigene Preisklasse, ab 8 Auktionen; sonst die ganze Liga.
  - Unter 8 Auktionen gibt es kein Modell.
  - Gleichstand gilt als verloren.
  - Auktionen ohne Gebote fehlen in den Daten. Die Schätzung ist dadurch eher vorsichtig.
- **Wert des Zuschlags (`worth`):**

  | Zweck | Wert |
  |---|---|
  | Gewinnhandel | Netto-Verkaufserlös |
  | Startelf | Verdrängter × Quote + `max_cost_per_point` × Punktgewinn (dein Preis je Punkt als Bewertung) |
  | Ersatz | `cover_max_price` |

- **Wahl:** Das Gebot zwischen Mindestgebot und Obergrenze mit dem höchsten `P(win) × (worth − Gebot)`, geprüft in bis zu 40 Schritten. Ziel ist nicht die höchste Gewinnquote, sondern der beste Erwartungswert.
- **Ohne Modell** (unter 8 Auktionen) und beim Gebot nach einem Platz-Verkauf (dort zählt eine hohe Chance): die gelernte Höhe `extra` zwischen `bid_low` und `bid_high` (siehe unten).

**Preis je Punkt (Startelf):**
- Formel: (Gebot − Marktwert des Verdrängten × konservative Quote) / Punktgewinn ≤ `max_cost_per_point`. Das ist die faire Transferdifferenz. Der Verdrängte wird dadurch **nicht** verkauft.
- Das zusätzlich gebundene Kapital ist das ganze Gebot. Es steht in der Begründung („bindet X Mio.“).

**Gebot** (`bid_for`):
- Mindestgebot `low` = max(`bid_low`, Preis, Marktwert).
- Gebot = `low` + `extra` × (`high` − `low`), aufgerundet auf 10.000 €.
- Liegt das Gebot über der kleinsten Obergrenze, wird es auf diese abgerundet. Liegt auch die Obergrenze unter dem Mindestgebot, gibt es kein Gebot. Ohne gültigen Preis ebenfalls kein Gebot.
- Obergrenzen:
  - Geld × Anteil.
  - Ersatz: `cover_max_price`.
  - Gewinnhandel: `profit_room` und `max_profit_bid`.
  - Startelf: Marktwert des Verdrängten + `max_cost_per_point` × Punkte.
- Lücken-Reserve: Je weitere Lücke bleiben `cover_max_price` zurück.

### 5.9 Verkauf für einen Platz

- Nur wenn kein Geld oder kein Platz da ist, die Auktion in ≤ `sell_window` Min. endet und das Tageslimit es erlaubt.
- `pick_sale` sieht **nur den bestätigten Kader**: Das Ziel zählt weder als Ersatz noch als Starter, die Auktion kann verloren gehen.
- Nie ein fitter Spieler der besten Elf (auch nicht der Verdrängte), nie der letzte fitte Ersatz, nie eine neue Lücke in der Elf.
- Erlaubt sind nur: verletzte Spieler, Nicht-Stammspieler, Bankspieler, deren Ziel um ≥ `swap_edge` mehr steigen soll.
- Direkt vor dem Verkauf wird geprüft, ob die Ziel-Auktion noch läuft (> 1 Min.).
- Der Verkauf bringt in dieser Runde kein Geld (`OVER_BUDGET` für das abhängige Gebot). Das Gebot folgt frühestens in der nächsten Runde mit bestätigtem Kontostand. Geht die Auktion verloren, bleibt die Mannschaft trotzdem abgesichert.

### 5.10 Ausstiegssystem für Gewinnpositionen (`exit_reason`)

Für jeden vom Trader gekauften Gewinnspieler, der noch im Kader ist, prüft der Trader jede Runde: halten oder verkaufen. Der Preis ist bis 22 Uhr ganztägig gleich.
- **Verkaufen** bringt sofort: Wert × Quote.
- **Halten** bringt später: `gain` × Quote, mit Risiko.

Der Kaufpreis kommt aus dem gewonnenen Gebot, sonst von Kickbase. Ist er unbekannt, wird nicht bewertet.

| Code | Grund | Bedingung |
|---|---|---|
| `SPORT` | sportlicher Ausfall | nicht fit |
| `STOP` | Positions-Stop-Loss | Netto-Verlust ≥ `position_stop` % des Kaufpreises und Prognose ≤ 0 |
| `TRAIL` | Trailing-Stop | Höchststand seit Kauf lag netto im Gewinn, Wert ≤ Höchststand × (1 − `trailing_stop` %), Prognose ≤ 0 |
| `TURN` | Prognosewechsel | Prognose < 0 **und** (heute gefallen oder Prognose ≤ −0,5 % des Werts). Ein einzelnes kleines Minus ist Rauschen |
| `TAKE` | Take-Profit | netto im Gewinn und Halten bringt weniger als die Mindestmarge |
| `TIME` | Zeitlimit | ≥ `max_hold_days` gehalten und Halten bringt weniger als die Mindestmarge |

- Pro Runde höchstens ein Ausstieg, der dringendste in der Reihenfolge der Tabelle.
- Nie ein gesperrter Spieler, nie einer der besten Elf, nie der letzte Ersatz. Das Urteil wird dann mit „geschützt“ protokolliert.
- Tageslimit `daily_sales` gilt.
- Das Urteil jeder Position steht im Debug-Protokoll (`positions`).
- Kapitalrotation, also Verkauf zugunsten eines besser rentierenden Ziels, läuft weiter über den Platz-Verkauf (5.9) mit der gelernten `swap_edge`.
- Sportliche Ausfälle von Nicht-Gewinnspielern werden nicht automatisch verkauft. Sie werden aber als erste für einen Platz abgegeben (5.9).

---

## 6. Risk Engine (`core/risk.py`)

Sie prüft alle Aktionen der Planung der Reihe nach mit laufenden Summen. So bleibt der Plan als Ganzes zulässig, auch wenn **jede** offene Auktion gewonnen wird. Dieselbe Prüfung gilt im Probelauf und live.

| Code | Bedeutung |
|---|---|
| `KILL_SWITCH` | Server-, Liga- oder Trader-Schalter aus |
| `BID_INVALID` | Gebot ≤ 0, unter dem Mindestgebot oder nicht auf 10.000 € gerundet |
| `AUCTION_EXPIRED` / `AUCTION_UNKNOWN` | Auktion abgelaufen / Ende unbekannt (Gewinnhandel) |
| `NOT_LISTED` | nicht auf dem Markt |
| `OVER_BUDGET` | Kontostand − alle offenen und neuen Gebote − Gebot < Reserve − zulässiger Kredit |
| `SQUAD_FULL` / `CLUB_FULL` | Kader- bzw. Vereinslimit inkl. aller offenen und neuen Gebote |
| `DAILY_BIDS` / `DAILY_SALES` | Tageslimits (Rettung ohne Verkaufslimit) |
| `BLOCKED` | Rückkaufsperre oder unklarer Aufruf |
| `PROFIT_NEGATIVE` | Netto-Gewinn unter Mindestmarge oder Mindestrendite |
| `PHASE` | Gewinn-Gebot in `final` oder vor der Deadline in `repay` |
| `NOT_OWNED` / `LOCKED` / `STARTER` / `BREAKS_COVER` / `NEW_GAP` | Verkaufsschutz |
| `MANUAL_BID` / `NOT_OPEN` | Zurückziehen nur eigener, offener Trader-Gebote |

Blockierte Aktionen erscheinen im Debug-Protokoll (`risk_blocked`) und in der Begründung des Spielers.

---

## 7. Ausführung und Transaktionsstatus

```
planned (Probelauf) │ pending ─► open (Gebot) / sold (Verkauf)
                    │         ├► failed (Kickbase lehnt ab: HTTP 4xx)
                    │         └► unknown (keine Antwort, Timeout, HTTP ≥ 500) ─► Abgleich (3.1)
```

- **Absicht vorher speichern:** `pending`, bevor Kickbase aufgerufen wird. Auch ein Absturz hinterlässt einen abgleichbaren Eintrag.
- **Verkauf:**
  - Vorher: Kontostand lesen. Bei Platz-Verkauf zusätzlich die Ziel-Auktion prüfen.
  - Nachher: Kontostand erneut lesen. Erlös = Differenz, sonst **unbekannt**.
  - Kaufpreis: aus dem gewonnenen Gebot dieser Besitzperiode, sonst aus dem Kader vor dem Verkauf.
  - Gewinn nur aus bekannten Zahlen.
  - Gelernt (Verkaufsquote, Marge) wird nur mit gebuchtem Erlös.
- **Gebot zurückziehen:** Angebots-ID frisch vom Markt holen, nur eigene Trader-Gebote. Ist das Gebot schon weg, wird übersprungen.
- **Ende der Runde:** nach jedem Verkauf und jedem nicht bestätigten Schritt. Die nächste Runde plant mit bestätigten Daten neu.
- **Probelauf:** Einträge `planned` zählen nicht für Tageslimits, Rückkaufsperre, Stop-Loss oder Gewinn.

---

## 8. Lernen

**Drei Ebenen:**

| Ebene | Speicher | Inhalt |
|---|---|---|
| Global (Basismodell) | `ModelState "trader"` | Prognose-Kalibrierung (`gain_ratio`, Richtung, Pause), `min_margin`, `swap_edge`, globale Gebotshöhen |
| Liga | `ModelState "trader:<liga>"` | eigene Gebotshöhen `extra` und Auktionszahlen (Bieterverhalten der Liga). Dazu kommt die Gewinnchance aus den Liga-Transfers (oben) |
| Nutzer/Liga | Einstellungen (`Options`) | Risikobereitschaft, Kapitalanteile, Schutzregeln |

- **Mischung (`blend`):** Gebotshöhe = w × Liga + (1 − w) × global, mit w = n / (n + 10). Dabei ist n die Zahl der Liga-Auktionen (Schatten zählen halb). Eine neue Liga startet also mit der globalen Erfahrung.
- **Jede Auktion lernt doppelt:** im globalen Modell und in ihrer Liga.
- **Bestehende Werte** bleiben als globales Basismodell erhalten (Migration ohne Datenverlust).

| Wert | Start | Grenzen | Regel |
|---|---|---|---|
| `extra[Klasse]` | 0,3 | 0–1 | gewonnen −0,05·w, an höheres Gebot verloren +0,15·w (w = 1 echt, 0,5 Schatten). Nur noch Rückfall, wenn das Gewinnchance-Modell fehlt |
| `min_margin` | 150.000 | 50.000–1,5 Mio. | Netto-Verlust × (1 + 0,05·w·(1 + Größe)) = +5…20 %; Netto-Gewinn × (1 − 0,01·w·(1 + Größe)) = −1…3 %. Größe = Ergebnis / Marge, höchstens 3. Ein kleiner Gewinn gleicht keinen großen Verlust aus |
| `gain_ratio` | 1,0 | −1…2 | EMA mit α = 0,1·w über (tatsächlich / Prognose) im selben Horizont (2 Updates); gespeichert wird die **unskalierte** Prognose |
| Prognose-Vertrauen | 1,0 | 0,3–1,0 | ab 10 Verläufen |
| `direction_hits` | 0 | ≥ 0 | Prognosen, deren Richtung stimmte; Trefferquote ab 10 Verläufen |
| `forecast_pause` | 0 | 0/1 | **Prognose-Pause:** Ab 10 Verläufen setzt `gain_ratio` < 0,3 den Gewinnhandel aus. Wieder an erst über 0,45 (Hysterese). Schattentransfers lernen weiter, so kann er zurückkehren |
| `swap_edge` | 100.000 | 50.000–1 Mio. | Halten hätte netto > 100.000 mehr gebracht → ×1,1, sonst ×0,97 (ohne Rettungsverkäufe) |

**Sicherheit des Lernens:**
- **Parallele Runden:** Lesen, Lernen und Schreiben laufen unter einer Sperre. Kein Update geht verloren; der Smoke-Test prüft das mit zwei Threads. Das gilt je Prozess, also für einen Container.
- **Versionierung:** Gespeicherte Zustände tragen `version: 2`. Ältere Zustände laden mit Standardwerten für neue Felder.
- **Laden und Import:** NaN, Infinity und falsche Typen werden verworfen, alle Werte begrenzt.
- **Zurücksetzen:** `POST /api/automation/trader/reset?scope=global|league` (nur Admins). Die alten Werte stehen im Ereignis `trader-import` und lassen sich zurückimportieren.

---

## 9. Einstellungen je Liga

| Schlüssel | Standard | Grenzen | Bedeutung |
|---|---|---|---|
| `min_gain` | 2,0 | 0–100 | Mindest-Punktgewinn bei Verbesserung |
| `max_cost_per_point` | 300.000 | 0–50 Mio. | Aufpreis je Punkt |
| `min_avg_edge` | 10 % | 0–200 | Schnitt über dem Verdrängten |
| `min_play` | 60 % | 0–100 | Einsatzquote |
| `lineup_share` | 100 % | 10–100 | Geldanteil je Startelf-/Ersatz-Gebot |
| `profit_share` | 60 % | 10–100 | **kumuliert**: Anteil von Mannschaftswert + Kontostand für alle Gewinnpositionen |
| `min_roi` | 2,0 % | 0–100 | Mindestrendite netto |
| `credit_mode` | 1 | 0–2 | 0 nie, 1 Startelf/Ersatz, 2 auch Gewinnhandel |
| `position_stop` | 10 % | 0–100 | Positions-Stop-Loss (0 = aus) |
| `trailing_stop` | 5 % | 0–50 | Trailing-Stop unter dem Höchststand (0 = aus) |
| `max_hold_days` | 7 | 0–60 | Zeitlimit für Gewinnpositionen (0 = aus) |
| `reserve` | 0 | 0–500 Mio. | nie ausgegeben |
| `cover_max_price` | 3 Mio. | 0–50 Mio. | Ersatz höchstens, Reserve je Lücke |
| `daily_bids` / `daily_sales` | 6 / 3 | 0–30 | Tageslimits (Berlin-Zeit) |
| `stop_loss` | 3 Mio. | 0–100 Mio. | Wochenverlust, ab dem Gewinnhandel pausiert (0 = aus) |
| `sell_window` | 20 Min. | 5–180 | Verkauf für Platz |
| `starter_lock` | 60 Min. | 0–1440 | Startelf-Sperre |
| `shadow` | an | true/false | Schattentransfers |
| `rescue_override` | aus | true/false | Notfallregel |

Booleans akzeptieren nur `true/false`, `1/0` und die gleichnamigen Texte. `"false"` ist also falsch.

**Feste Regeln:**
- Haltedauer der Prognose: 2 Updates.
- Rückkaufsperre: 7 Tage. Mindesthaltezeit: 20 Std.
- Startelf wieder verkäuflich: 5 Min. nach dem Anpfiff.
- `ROOM_EXTRA`: 0,6. Lernschwelle: 10 Verläufe. Schatten-Gewicht: 0,5.
- Preisklassen: < 5 Mio., 5–15 Mio., ≥ 15 Mio.
- Gebotsschritt: 10.000 €. Verkaufsquote höchstens 0,9.
- Abgleich unklarer Aufrufe: nach 10 Min. Pause: ab 3 Fehlern pro Stunde.
- Phasen: 24 Std. / letztes Update / 60 Min.
- Qualität: 0,6 × Schnitt + 0,4 × Form. Wenig Daten: unter 3 Einsätzen ×1,5 Mindestgewinn.
- Vorschau: 3 Spiele. Prognosewechsel: 0,5 %.
- Gewinnchance-Modell ab 8 Auktionen, 40 Gebotsschritte.
- Liga-Gewicht: n / (n + 10).
- Prognose-Pause unter 0,3, wieder an über 0,45.

---

## 10. Export, Import, Debug

- **Export** (`GET /api/automation/trader/export?days=1–60`): Erklärtext, Schalter, Einstellungen, gelernte Werte, feste Regeln, Trades, Schatten, Ereignisse, Debug-Runden. Keine Tokens oder Zugangsdaten.
- **Import** (`POST /api/automation/trader/import`):
  - `options` gilt für die eigene Liga, `learned` nur für Admins (`403` sonst).
  - Die Werte **vorher** landen im Ereignis `trader-import`. Wer sie zurückimportiert, stellt den alten Stand wieder her.
- **Debug-Runde** (`TraderDebug`, 21 Tage, nur bei Änderung):
  - Phase, aktive Prioritäten, Kontostand, Worst Case, `cash_free`, Kredit, `credit_mode`, Liquidationswert, `profit_room`.
  - Wochenergebnis und Buchverlust (Stop-Loss), jede Gewinnposition mit Kaufpreis, Netto jetzt und Urteil.
  - Je Marktspieler zusätzlich `ahead`, `samples`, `quality` und `p_win_at_low` (Gewinnchance beim Mindestgebot).
  - Je Runde: `league_auctions` (Datenbasis des Gewinnchance-Modells), `forecast_paused` und die verwendeten gelernten Werte.
  - Export: `learned` (global), `learned_league`, `learned_effective`.
  - Offene Gebote, Limits, Pause, Startelf-Sperre, ob die Aufstellung lesbar war.
  - Kader, offene Gebote, Marktspieler mit `net_at_low`, Geld und Begründung.
  - `risk_blocked` mit Code, freigegebene Aktionen.

---

## 11. Nicht verifizierte Kickbase-Annahmen (Fail-Closed)

Gegen die echte Kickbase-API lässt sich das ohne Live-Zugang nicht prüfen. Die API-Dokumentation (kevinskyba/kickbase-api-doc) beschreibt die betreffenden Antworten nicht.

| Annahme | Wenn sie falsch ist | Absicherung |
|---|---|---|
| Max-Gebot = 33-%-Regel wie in `analytics.max_bid` | Kredit zu groß oder zu klein | Kredit zusätzlich durch die Liquidation begrenzt. `credit_mode 0` schaltet ihn ganz ab |
| Offene Gebote sind im Kontostand **nicht** abgezogen | doppelt abgezogen → zu vorsichtig | konservative Richtung |
| Gewonnene Auktion wird erst beim Zuschlag abgebucht, mehrere Zuschläge zugleich möglich | – | Worst Case nimmt alle Zuschläge an |
| Sofortverkauf ≈ 90 % des Marktwerts oder weniger | Erlös anders | Quote nie über 0,9, gelernt nur nach unten. Erlös wird nach dem Verkauf gemessen |
| Kein Abruf des Verkaufspreises vorab | – | Schätzung, danach Messung |
| 0 Punkte nur bei negativem Kontostand **zum Anpfiff** | anderer Prüfzeitpunkt | Rückzahlung ab Vorabend, Push-Warnung |
| Verkauf eines Starters 5 Min. nach Anpfiff behält seine Punkte | Punktverlust | Angabe des Nutzers. Sperre einstellbar (`starter_lock`) |
| Gebote zurückziehen per `DELETE …/offers/{id}` | Zurückziehen scheitert | Ergebnis über den Markt geprüft. Gebot bleibt sonst offen und wird als ausgegeben gezählt |
| Antwort der gespeicherten Aufstellung (`lo`-Plätze) | Aufstellung unbekannt | Dann gilt jeder fitte Spieler als gesperrt |
| Gleichstand, Ändern von Geboten | unbekannt | nicht genutzt |

---

## 12. Bekannte Grenzen

- Pro Lücke wird nur einmal geboten. Ein verlorenes Gebot wird frühestens in der nächsten Runde ersetzt.
- Das Lernen der Prognose, der Marge und der Tausch-Schwelle ist für alle Nutzer gemeinsam. Gebotshöhen sind je Liga getrennt, die Gewinnchance kommt aus den Liga-Transfers.
- **Höhere Startelf-Gebote:** Das Gebot nach Erwartungswert nutzt bei Startelf-Käufen deinen Preis je Punkt als Bewertung. Ist `max_cost_per_point` großzügig, fällt das Gebot höher aus als früher, weil es die Gewinnchance stärker gewichtet. In der Demo stieg ein Gebot so von 8,74 auf 9,81 Mio.
- Gebotsgleichstände und Auktionen ohne Gebote sind in den Daten nicht sichtbar. Beide Lücken wirken vorsichtig.
- Läuft der Server vom Vorabend bis zur Deadline durchgehend nicht, bleibt ein Minus stehen.
- Rettungsverkäufe nutzen eine gierige Auswahl, kein kombinatorisches Optimum.
- Kein Backtesting, keine Strategieprofile (Meilensteine 3–4). Die Gewichte und Schwellen von Meilenstein 2 sind begründete Startwerte, aber noch nicht kalibriert:
  - Qualität 0,6 / 0,4,
  - Faktor 1,5 bei wenig Daten,
  - Trailing-Stop 5 %, Positions-Stop 10 %, Zeitlimit 7 Tage.
- Die Vorschau über 3 Spiele nimmt den heutigen Status als dauerhaft an und kennt keine Rotation.
- Mehrere Backend-Instanzen: Die Rundensperre gilt je Prozess. Empfohlen ist ein Container.
