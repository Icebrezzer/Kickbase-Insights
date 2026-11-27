# Arbeitspakete

Eine Datei je Epic (`E<nn>-<name>.md`), darin ein strukturierter Eintrag je Arbeitspaket. Gesamtübersicht, Priorität und Abhängigkeitsmatrix: `../MASTERPLAN.md`.

## Status

`todo` → `ready` (Abhängigkeiten erfüllt) → `in_progress` → `review` → `done` · Sonderfälle: `blocked` (Grund im Eintrag), `dropped` (Begründung in `DECISIONS.md`).

## Priorität

`P1` sofortiger Nutzen oder Voraussetzung für viele Pakete · `P2` wichtig, nach P1 · `P3` Ausbau.

## Aufwand

`S` < 150 Zeilen · `M` 150–400 · `L` > 400 → muss vor Beginn geteilt werden.

## Vorlage

```markdown
### E<nn>.<mm> – Titel
- **Priorität:** P? · **Status:** todo · **Abhängig von:** – · **Aufwand:** S/M · **Flag:** – / name
- **Ausgangssituation:** …
- **Ziel:** ein Satz.
- **Umfang:** …
- **Nicht enthalten:** …
- **Module:** …
- **Sicherheit:** berührte Regeln S? aus SAFETY_RULES.md, wie geprüft.
- **Abnahmekriterien:** 1. … 2. …
- **Pflichttests:** …
- **Migration:** keine / …
- **Rollback:** …
- **Ergebnis:** (Tests, Messwerte, ausdrücklich „nicht ausgeführt“, wo zutreffend) · **Commit:** – · **Offene Risiken:** –
```
