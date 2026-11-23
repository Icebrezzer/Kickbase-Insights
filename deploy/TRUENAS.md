# Installation auf TrueNAS SCALE 25.10

## 1. Image
GitHub Actions baut bei jedem Push auf `main` das Image `ghcr.io/icebrezzer/kickbase-insights:latest`
(Workflow „Build“). Falls TrueNAS das Image nicht laden darf: auf GitHub unter *Packages →
kickbase-insights → Package settings* die Sichtbarkeit auf **Public** stellen.

## 2. Custom App
*Apps → Discover Apps → ⋮ → Install via YAML* und den Inhalt von `truenas-custom-app.yaml`
einfügen. Platzhalter `<...>` ersetzen.

Läuft das Original von casudo schon: Image-Zeile und die neuen Variablen (`KBI_PUSH__SUBJECT`,
`KBI_ALLOW__BALANCES_USERS`) in die bestehende App übernehmen und **denselben `/data`-Pfad** behalten.
Die neuen Tabellen werden beim Start angelegt, bestehende Daten bleiben.

Der Datenordner muss UID/GID 1000 gehören (der Container läuft als Benutzer `kbi`):

```sh
chown -R 1000:1000 /mnt/<pool>/apps/kickbase-insights
```

## 3. Reverse Proxy
`kickbase.bananaflixx.eu` → `http://<truenas-ip>:8000`. HTTPS ist Pflicht für Push und die
Home-Bildschirm-App.

## 4. iPhone
1. In Safari `https://kickbase.bananaflixx.eu` öffnen und anmelden.
2. Teilen → **Zum Home-Bildschirm**.
3. Die App vom Home-Bildschirm öffnen → *Mehr → Automatik & Push* → **Auf diesem Gerät aktivieren**
   → Mitteilungen erlauben → **Testnachricht**.

## 5. Automatik einschalten
*Automatik & Push*, pro Liga:
- **Beste Elf automatisch aufstellen**: Prüft nach jedem Sync, bis zur Deadline alle 30 Min., in den
  letzten 3 Std. alle 5 Min.
- **Deadline-Warnungen**: Push 180/60/15 Min. vor dem ersten Anpfiff, wenn etwas nicht passt.
- **Transferziele auf die Scoutingliste**: Schwelle (Standard 250.000 €) und Höchstzahl einstellbar.

Für Mitspieler läuft die Automatik, solange ihre Anmeldung gültig ist. Die App warnt zwei Tage vor
Ablauf per Push.

## Quoten prüfen
Die App fragt Kickbases Wett-Link jedes Spiels ab. Was Kickbase dort liefert, ist nicht dokumentiert:
`https://kickbase.bananaflixx.eu/api/odds/sample` zeigt die gespeicherten Antworten. Enthalten sie
keine Quoten, kann ein kostenloser Schlüssel von the-odds-api.com als `KBI_ODDS__API_KEY` gesetzt werden.

## Erste echte Läufe prüfen
Speichern der Aufstellung und Sofortverkauf nutzen Kickbase-Schnittstellen, die nur von der
Community dokumentiert sind. Die Antwort von Kickbase steht im Protokoll (*Automatik → Protokoll*).
Nach dem ersten Speichern der Aufstellung in der Kickbase-App gegenprüfen.

## Optionale Einstellungen
| Variable | Standard | Wirkung |
|---|---|---|
| `KBI_AUTOMATION__INTERVAL_MINUTES` | 5 | Wie oft die Automatik läuft |
| `KBI_AUTOMATION__LINEUP_CHECK_MINUTES` | 30 | Aufstellungs-Check, solange die Deadline weit weg ist |
| `KBI_AUTOMATION__LINEUP_CHECK_MINUTES_CLOSE` | 5 | …in den letzten `CLOSE_HOURS` Stunden |
| `KBI_AUTOMATION__CLOSE_HOURS` | 3 | |
| `KBI_AUTOMATION__ALERT_MINUTES` | 180,60,15 | Zeitpunkte der Deadline-Warnungen |
| `KBI_AUTOMATION__MARKET_WATCH_MINUTES` | 10 | Wie oft der Markt auf neue Listings geprüft wird |
| `KBI_AUTOMATION__MAX_SQUAD_SIZE` | 18 | Kadergröße der Liga (für Kaufplaner und Bieter) |
| `KBI_AUTOMATION__SELL_ADVICE_HOUR` | 20 | Uhrzeit der täglichen Verkaufsempfehlung |
| `KBI_ODDS__API_KEY` | – | Optional: Schlüssel von the-odds-api.com, falls Kickbase keine Quoten liefert |
| `KBI_SYNC__SCHEDULE` | `10 2,6,10,14,18,22 * * *` | Voller Abgleich (22:10 = direkt nach dem Marktwert-Update) |
