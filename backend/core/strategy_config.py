"""Strategy configuration schema, version 1 (E02.01).

One definition of every strategy setting: its place in the configuration (a dotted path, grouped as in
docs/autotrader/CONFIG_SCHEMA.md), type, unit, bounds, default and a German explanation. The league
options of 2.0 (core.trader.Options) are the editable fields; their default and bounds are taken from
Options and OPTION_LIMITS, so they can never drift apart. Fixed rules of the code are in the schema too,
read-only (`fixed`): they are documented and exported, and become editable one by one in own packages.

A configuration is a nested dict {"schema_version": 1, "finance": {...}, ...}. This module converts it
from and to Options and validates imports strictly (E02.02); storing it comes with E02.03.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, fields

from core import trader as t

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Setting:
    path: str # Dotted place in the configuration, e.g. "finance.reserve"
    kind: str # int, float, bool or choice
    unit: str
    text: str
    option: str | None = None # The core.trader.Options field it is, None for a fixed rule
    fixed_value: float | int | None = None # The value of a fixed rule
    choices: tuple[int, ...] = ()

    @property
    def fixed(self) -> bool:
        return self.option is None

    @property
    def default(self) -> float | int | bool:
        return self.fixed_value if self.option is None else getattr(t.Options(), self.option)

    @property
    def bounds(self) -> tuple[float, float] | None:
        if self.option is None or self.kind == "bool":
            return None
        return t.OPTION_LIMITS[self.option]


def _o(path: str, option: str, kind: str, unit: str, text: str, choices: tuple[int, ...] = ()) -> Setting:
    return Setting(path, kind, unit, text, option=option, choices=choices)


def _fixed(path: str, value: float | int, kind: str, unit: str, text: str) -> Setting:
    return Setting(path, kind, unit, text, fixed_value=value)


SETTINGS: tuple[Setting, ...] = (
    ### Finance
    _o("finance.reserve", "reserve", "int", "€", "Geld, das nie ausgegeben wird"),
    _o("finance.credit_mode", "credit_mode", "choice", "", "Kredit: 0 nie, 1 für Startelf und Ersatz, 2 auch für Gewinnhandel", (0, 1, 2)),
    _o("finance.lineup_cash_share_pct", "lineup_share", "int", "%", "Anteil des freien Geldes je Startelf- oder Ersatzgebot"),
    _o("finance.sell_ratio_pct", "sell_ratio", "int", "%", "Sofortverkauf bringt diesen Anteil des Marktwerts (Kickbase: 100)"),
    ### Profit trading
    _o("profit.max_total_share_pct", "profit_share", "int", "%", "Alle Gewinnpositionen zusammen höchstens dieser Anteil von Teamwert + Kontostand"),
    _o("profit.min_roi_pct", "min_roi", "float", "%", "Mindestrendite netto, bezogen auf das Gebot"),
    _o("profit.weekly_stop_loss", "stop_loss", "int", "€", "Wochenverlust, ab dem der Gewinnhandel pausiert (0 = aus)"),
    _o("profit.trailing_stop_pct", "trailing_stop", "int", "%", "Verkauf, wenn der Wert so weit unter den Höchststand seit dem Kauf fällt (0 = aus)"),
    _o("profit.position_stop_pct", "position_stop", "int", "%", "Verkauf bei so viel Netto-Verlust auf den Kaufpreis (0 = aus)"),
    _o("profit.max_hold_days", "max_hold_days", "int", "Tage", "Höchstens so lange halten, wenn kaum noch Gewinn zu erwarten ist (0 = aus)"),
    _fixed("profit.hold_updates", t.PROFIT_HOLD, "int", "Updates", "Prognosehorizont eines Gewinnkaufs"),
    ### Lineup
    _o("sport.min_points_gain", "min_gain", "float", "Punkte", "Mindest-Plus an erwarteten Punkten der Elf bei einem Tausch"),
    _o("sport.max_cost_per_point", "max_cost_per_point", "int", "€", "Höchster Mehrpreis je zusätzlichem Punkt"),
    _o("sport.min_quality_edge_pct", "min_avg_edge", "int", "%", "Punkteschnitt und Form mindestens so viel besser als beim Verdrängten"),
    _o("sport.min_play_pct", "min_play", "int", "%", "Mindest-Einsatzquote der letzten 5 Vereinsspiele"),
    _o("sport.upgrade_cross_position", "upgrade_cross_position", "bool", "", "Formationswechsel nach Punkten statt nach dem Schnitt des Verdrängten bewerten"),
    ### Bench
    _o("bench.max_price", "cover_max_price", "int", "€", "Höchstpreis für einen Ersatzspieler, Rücklage je Lücke"),
    ### Auctions
    _o("auction.room_sale_window_min", "sell_window", "int", "Min.", "Verkauf für einen Kaderplatz erst so kurz vor Auktionsende"),
    _fixed("auction.room_bid_extra", t.ROOM_EXTRA, "float", "", "Gebotshöhe nach einem Verkauf für einen Platz (0–1 zwischen Mindest- und Höchstgebot)"),
    _fixed("auction.min_auctions", t.MIN_AUCTIONS, "int", "Auktionen", "Ab so vielen Liga-Auktionen gilt das Gewinnchance-Modell"),
    _fixed("auction.bid_grid", t.BID_GRID, "int", "Schritte", "Geprüfte Gebotshöhen für das Gebot nach Erwartungswert"),
    ### Learning
    _o("learning.shadow_enabled", "shadow", "bool", "", "Schattentransfers verfolgen und daraus lernen"),
    _fixed("learning.min_samples", t.MIN_SAMPLES, "int", "Verläufe", "Ab so vielen Verläufen gelten gelernte Prognosewerte"),
    _fixed("learning.shadow_weight", t.SHADOW_WEIGHT, "float", "", "Lerngewicht eines Schattentransfers gegenüber einem echten"),
    ### Matchday
    _o("matchday.starter_lock_min", "starter_lock", "int", "Min.", "Stammspieler-Sperre vor dem ersten Anpfiff"),
    _o("matchday.rescue_override", "rescue_override", "bool", "", "Notfallregel: Rettungsverkäufe dürfen gesperrte Spieler verkaufen"),
    _fixed("matchday.prepare_hours", int(t.PREPARE_BEFORE.total_seconds() // 3600), "int", "Std.", "Vorbereitung vor der Deadline: kein Kredit für Gewinnhandel"),
    _fixed("matchday.final_minutes", int(t.FINAL_BEFORE.total_seconds() // 60), "int", "Min.", "Letzte Phase vor der Deadline: keine Gewinn-Gebote, kein Kredit"),
    _fixed("matchday.min_hold_hours", int(t.MIN_HOLD.total_seconds() // 3600), "int", "Std.", "Eigene Käufe werden mindestens so lange gehalten (außer verletzt)"),
    _fixed("matchday.rebuy_block_days", t.REBUY_BLOCK.days, "int", "Tage", "Kein Rückkauf eines verkauften Spielers innerhalb dieser Zeit"),
    ### Limits
    _o("limits.daily_bids", "daily_bids", "int", "", "Gebote pro Tag"),
    _o("limits.daily_sales", "daily_sales", "int", "", "Verkäufe pro Tag (Rettungsverkäufe ausgenommen)"),
)

BY_PATH = {s.path: s for s in SETTINGS}
BY_OPTION = {s.option: s for s in SETTINGS if s.option}


def _put(data: dict, path: str, value: object) -> None:
    section, key = path.split(".", 1)
    data.setdefault(section, {})[key] = value


def get(data: dict, path: str) -> object:
    """The value at `path`, or None when the configuration has none there."""
    section, key = path.split(".", 1)
    part = data.get(section)
    return part.get(key) if isinstance(part, dict) else None


def from_options(opts: t.Options) -> dict:
    """The configuration of these options, fixed rules at their values."""
    data: dict = {"schema_version": SCHEMA_VERSION}
    for s in SETTINGS:
        _put(data, s.path, s.default if s.fixed else getattr(opts, s.option))
    return data


def default() -> dict:
    return from_options(t.Options())


def to_options(data: dict) -> t.Options:
    """The league options of a configuration, as tolerant as Options.load: missing or junk values keep
    their default, every value is clamped. Fixed rules are not options and are ignored here."""
    return t.Options.load({s.option: get(data, s.path) for s in SETTINGS if s.option})


def schema() -> dict:
    """The schema as JSON for the UI, the docs and an outside review."""
    return {
        "schema_version": SCHEMA_VERSION,
        "settings": [
            {
                "path": s.path, "kind": s.kind, "unit": s.unit, "text": s.text, "default": s.default, "fixed": s.fixed,
                "min": s.bounds[0] if s.bounds else None, "max": s.bounds[1] if s.bounds else None,
                "choices": list(s.choices) or None, "option": s.option,
            }
            for s in SETTINGS
        ],
    }


def unmapped_options() -> set[str]:
    """Options fields without a place in the schema: must stay empty (checked by the tests)."""
    return {f.name for f in fields(t.Options)} - set(BY_OPTION)


### ===============================================================================
### Strict validation of imports (E02.02, ADR-004)
### ===============================================================================


def _check(s: Setting, value: object) -> tuple[object, str | None]:
    """The value as stored, or an error message in German. No clamping, no guessing."""
    if s.kind == "bool":
        return (value, None) if isinstance(value, bool) else (None, "muss true oder false sein")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None, "muss eine Zahl sein"
    if not math.isfinite(value):
        return None, "muss eine endliche Zahl sein"
    if s.kind in ("int", "choice"):
        if value != int(value):
            return None, "muss eine ganze Zahl sein"
        value = int(value)
    if s.fixed:
        return (value, None) if value == s.default else (None, f"ist eine feste Regel ({s.default}) und nicht änderbar")
    if s.kind == "choice":
        return (value, None) if value in s.choices else (None, f"erlaubt sind {', '.join(map(str, s.choices))}")
    low, high = s.bounds
    if not low <= value <= high:
        return None, f"muss zwischen {low:g} und {high:g} liegen"
    return (float(value) if s.kind == "float" else value), None


def upgrade(data: dict) -> dict:
    """A configuration of an older format in the current one: the flat options of 2.0 (an export's
    "options") become schema version 1. Unknown keys stay, so the validation can name them."""
    if "schema_version" in data:
        return data
    nested: dict = {"schema_version": SCHEMA_VERSION}
    for key, value in data.items():
        setting = BY_OPTION.get(key)
        if setting is None:
            nested.setdefault("_unknown", {})[key] = value
        else:
            _put(nested, setting.path, value)
    return nested


def validate(data: object, base: dict | None = None) -> tuple[dict | None, list[dict]]:
    """A complete configuration from `data` on top of `base` (default: the default configuration), or
    None and every error with its path. Strict, for imports and the UI: nothing is taken over while any
    error is left. Missing settings keep the value of `base`."""
    if not isinstance(data, dict):
        return None, [{"path": "", "message": "muss ein JSON-Objekt sein"}]
    data = upgrade(data)
    errors: list[dict] = []
    version = data.get("schema_version")
    if isinstance(version, bool) or not isinstance(version, int):
        errors.append({"path": "schema_version", "message": "muss eine ganze Zahl sein"})
    elif version > SCHEMA_VERSION:
        errors.append({"path": "schema_version", "message": f"Version {version} ist neuer als diese App ({SCHEMA_VERSION})"})
    elif version < 1:
        errors.append({"path": "schema_version", "message": "unbekannte Version"})
    result = {**(base or default())}
    result = {k: dict(v) if isinstance(v, dict) else v for k, v in result.items()}
    result["schema_version"] = SCHEMA_VERSION
    for key in data.get("_unknown") or {}:
        errors.append({"path": key, "message": "unbekannte Einstellung"})
    sections = {s.path.split(".", 1)[0] for s in SETTINGS}
    for section, part in data.items():
        if section in ("schema_version", "_unknown"):
            continue
        if section not in sections:
            errors.append({"path": section, "message": "unbekannter Bereich"})
            continue
        if not isinstance(part, dict):
            errors.append({"path": section, "message": "muss ein JSON-Objekt sein"})
            continue
        for key, value in part.items():
            path = f"{section}.{key}"
            setting = BY_PATH.get(path)
            if setting is None:
                errors.append({"path": path, "message": "unbekannte Einstellung"})
                continue
            checked, error = _check(setting, value)
            if error:
                errors.append({"path": path, "message": error})
            else:
                _put(result, path, checked)
    return (None, errors) if errors else (result, [])
