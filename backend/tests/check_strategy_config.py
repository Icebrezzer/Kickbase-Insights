"""Strategy configuration schema (E02.01): one definition, the same defaults and bounds as 2.0.

    python tests/check_strategy_config.py
"""

from __future__ import annotations

import json
import sys
from dataclasses import fields
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import strategy_config as sc  # noqa: E402
from core import trader as t  # noqa: E402

passed = 0


def ok(condition: bool, label: str) -> None:
    global passed
    if not condition:
        raise SystemExit(f"FAILED: {label}")
    passed += 1


def main() -> None:
    ### Every league option has exactly one place, paths are unique, every setting has a text
    ok(not sc.unmapped_options(), f"every option is in the schema ({sc.unmapped_options()})")
    ok(len(sc.BY_PATH) == len(sc.SETTINGS) and len(sc.BY_OPTION) == len(fields(t.Options)), "paths and options unique")
    ok(all(s.text and "." in s.path and s.kind in ("int", "float", "bool", "choice") for s in sc.SETTINGS), "every setting is described")
    ### Defaults and bounds are those of 2.0
    ok(sc.to_options(sc.default()) == t.Options(), "the default configuration is the default options")
    for name in t.PROFILES:
        opts = t.profile(name)
        ok(sc.to_options(sc.from_options(opts)) == opts, f"profile {name} round trip")
    custom = t.Options.load({"sell_ratio": 100, "upgrade_cross_position": True, "reserve": 2_000_000, "min_roi": 3.0, "credit_mode": 2})
    ok(sc.to_options(sc.from_options(custom)) == custom, "custom options round trip")
    for s in sc.SETTINGS:
        if s.option and s.kind != "bool":
            ok(s.bounds == t.OPTION_LIMITS[s.option], f"bounds of {s.path}")
    ok(sc.BY_PATH["finance.credit_mode"].choices == (0, 1, 2), "credit mode choices")
    ### Fixed rules carry the code's values and are not options
    ok(sc.BY_PATH["profit.hold_updates"].fixed and sc.BY_PATH["profit.hold_updates"].default == t.PROFIT_HOLD, "hold updates fixed at 2")
    ok(sc.BY_PATH["matchday.min_hold_hours"].default == 20 and sc.BY_PATH["matchday.rebuy_block_days"].default == 7, "hold and rebuy rules")
    ok(sc.BY_PATH["matchday.prepare_hours"].default == 24 and sc.BY_PATH["matchday.final_minutes"].default == 60, "phase rules")
    ### Tolerant conversion like Options.load: junk keeps the default, out of bounds is clamped
    junk = sc.default()
    junk["finance"]["reserve"] = "viel"
    junk["profit"]["min_roi_pct"] = float("nan")
    junk["limits"]["daily_bids"] = 999
    opts = sc.to_options(junk)
    ok(opts.reserve == 0 and opts.min_roi == 2.0 and opts.daily_bids == 30, "junk keeps the default, too much is clamped")
    ok(sc.to_options({}) == t.Options(), "an empty configuration is the default")
    ok(sc.get(sc.default(), "finance.reserve") == 0 and sc.get({}, "finance.reserve") is None, "reading a path")
    ### The schema as JSON
    schema = json.loads(json.dumps(sc.schema()))
    ok(schema["schema_version"] == 1 and len(schema["settings"]) == len(sc.SETTINGS), "schema as JSON")
    fixed = [s for s in schema["settings"] if s["fixed"]]
    ok(len(fixed) == sum(1 for s in sc.SETTINGS if s.fixed) and all(s["option"] is None for s in fixed), "fixed rules marked")

    ### E02.02: strict validation of imports. Every error has its path, nothing is taken over with an error
    good, errors = sc.validate({"schema_version": 1, "finance": {"reserve": 1_000_000, "sell_ratio_pct": 100}})
    ok(not errors and sc.get(good, "finance.reserve") == 1_000_000 and sc.to_options(good).sell_ratio == 100, "a valid partial import")
    ok(sc.get(good, "limits.daily_bids") == 6, "missing settings keep the base")
    base = sc.from_options(t.Options(daily_bids=9))
    merged, _ = sc.validate({"schema_version": 1, "finance": {"reserve": 5}}, base)
    ok(sc.get(merged, "limits.daily_bids") == 9 and sc.get(base, "finance.reserve") == 0, "merged on the base, the base unchanged")
    bad_cases = {
        "finance.reserve": ("viel", "muss eine Zahl sein"),
        "profit.min_roi_pct": (float("nan"), "endliche"),
        "limits.daily_bids": (999, "zwischen 0 und 30"),
        "limits.daily_sales": (2.5, "ganze Zahl"),
        "finance.credit_mode": (3, "erlaubt sind 0, 1, 2"),
        "learning.shadow_enabled": ("false", "true oder false"),
        "sport.min_play_pct": (True, "muss eine Zahl sein"),
        "profit.hold_updates": (3, "feste Regel"),
        "finance.nope": (1, "unbekannte Einstellung"),
    }
    for path, (value, message) in bad_cases.items():
        section, key = path.split(".")
        result, errors = sc.validate({"schema_version": 1, section: {key: value}, "finance": {"reserve": 1} if section != "finance" else {key: value}})
        ok(result is None and any(e["path"] == path and message in e["message"] for e in errors), f"refused: {path}={value!r} ({errors})")
    ok(sc.validate({"schema_version": 1, "profit": {"hold_updates": 2}})[1] == [], "a fixed rule at its value is fine")
    for doc, path, message in (
        ([1, 2], "", "JSON-Objekt"), ({"schema_version": 2}, "schema_version", "neuer"), ({"schema_version": "1"}, "schema_version", "ganze Zahl"),
        ({"schema_version": 1, "casino": {}}, "casino", "unbekannter Bereich"), ({"schema_version": 1, "finance": 5}, "finance", "JSON-Objekt"),
    ):
        result, errors = sc.validate(doc)
        ok(result is None and errors and errors[0]["path"] == path and message in errors[0]["message"], f"refused: {doc} ({errors})")
    ### Several errors at once, all named, nothing taken over
    result, errors = sc.validate({"schema_version": 1, "finance": {"reserve": -1, "credit_mode": 7}, "limits": {"daily_bids": 5}})
    ok(result is None and {e["path"] for e in errors} == {"finance.reserve", "finance.credit_mode"}, "every error named, none taken over")
    ### The flat options of a 2.0 export are recognized and checked the same way
    old, errors = sc.validate({"min_gain": 10.0, "reserve": 2_000_000, "min_roi": 3.0})
    ok(not errors and sc.to_options(old).min_gain == 10.0 and sc.to_options(old).reserve == 2_000_000, "2.0 options upgraded")
    _, errors = sc.validate({"min_gain": 500, "nope": 1})
    ok({e["path"] for e in errors} == {"sport.min_points_gain", "nope"}, f"2.0 options checked strictly ({errors})")
    full = sc.from_options(t.profile("aggressive"))
    again, errors = sc.validate(full)
    ok(not errors and sc.to_options(again) == t.profile("aggressive"), "a complete configuration validates as it is")

    ### E02.05: the preview names every changed setting with before and after, nothing else
    base = sc.default()
    after, _ = sc.validate({"schema_version": 1, "finance": {"reserve": 1_000_000}, "limits": {"daily_bids": 6}}, base)
    changes = sc.diff(base, after)
    ok(changes == [{"path": "finance.reserve", "text": sc.BY_PATH["finance.reserve"].text, "unit": "€", "before": 0, "after": 1_000_000}],
       f"only the changed setting ({changes})")
    ok(sc.diff(base, base) == [], "no change, no diff")

    print(f"All {passed} strategy config checks passed.")


if __name__ == "__main__":
    main()
