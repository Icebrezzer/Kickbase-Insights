"""Feature flags (E02.08): off by default, strict import, live only with live trading.

    python tests/check_feature_flags.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import flags  # noqa: E402

passed = 0


def ok(condition: bool, label: str) -> None:
    global passed
    if not condition:
        raise SystemExit(f"FAILED: {label}")
    passed += 1


def main() -> None:
    ok(flags.FLAGS and all(text for text in flags.FLAGS.values()), "every flag is described")
    ok(flags.load(None) == dict.fromkeys(flags.FLAGS, flags.OFF), "nothing stored: every flag off")
    loaded = flags.load({"flexible_bench": "shadow", "nope": "live", "decision_snapshots": "maybe", "upgrade_financing": True})
    ok(loaded["flexible_bench"] == "shadow" and "nope" not in loaded, "stored stages load, unknown names dropped")
    ok(loaded["decision_snapshots"] == "off" and loaded["upgrade_financing"] == "off", "junk stages count as off")
    ### Strict for imports
    ok(flags.validate({"flexible_bench": "dry_run"}) == ({"flexible_bench": "dry_run"}, []), "a valid change")
    changes, errors = flags.validate({"flexible_bench": "on", "casino": "live"})
    ok(changes is None and {e["path"] for e in errors} == {"flags.flexible_bench", "flags.casino"}, f"every error named ({errors})")
    ok(flags.validate("live")[0] is None and flags.validate([])[0] is None, "no object, no change")
    ok(flags.validate({}) == ({}, []), "an empty change is fine")
    ### live needs live trading, otherwise it plans only
    stored = {"flexible_bench": "live", "decision_snapshots": "shadow"}
    ok(flags.effective(stored, "flexible_bench", True) == "live", "live with live trading")
    ok(flags.effective(stored, "flexible_bench", False) == "dry_run", "live without live trading is a dry run")
    ok(flags.effective(stored, "decision_snapshots", False) == "shadow", "shadow stays shadow")
    ok(flags.effective(stored, "conditional_repayment", True) == "off", "a flag not set is off")
    ok(set(flags.all_effective(stored, False)) == set(flags.FLAGS), "all flags with their stage")
    print(f"All {passed} feature flag checks passed.")


if __name__ == "__main__":
    main()
