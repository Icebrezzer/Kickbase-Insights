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

    print(f"All {passed} strategy config checks passed.")


if __name__ == "__main__":
    main()
