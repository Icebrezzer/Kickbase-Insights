"""Feature flags of the autotrader, per user and league (E02.08, ADR-002).

Every new trading function is installed switched off and goes through four stages:
off (installed, does nothing), shadow (computes alongside, changes nothing), dry_run (plans, sends
nothing to Kickbase), live (really trades). `live` only takes effect when the league's switch "Live
handeln" is on as well; otherwise the flag works as dry_run at most.

New flags are added here only, with a German explanation; unknown flags in an import are refused.
With a flag off the trader behaves exactly as without the function (tested in each package).
"""

from __future__ import annotations

OFF, SHADOW, DRY_RUN, LIVE = "off", "shadow", "dry_run", "live"
STAGES = (OFF, SHADOW, DRY_RUN, LIVE)

### Name -> what it switches. Planned functions are listed before they exist, so a configuration can
### already carry them; each stays without effect until its package is done
FLAGS: dict[str, str] = {
    "decision_snapshots": "Entscheidungs-Snapshots aller Kandidaten speichern (E03.01)",
    "flexible_bench": "Konfigurierbare Ersatzbank statt voller Positionsabsicherung (E05.02)",
    "multi_day_liquidation": "Kredit mit allen Verkaufsmöglichkeiten bis zur Deadline (E04.02)",
    "scenario_credit": "Kredit nur auf den pessimistisch bewerteten Verkaufserlösen (E04.03)",
    "early_repayment": "Ein bestätigtes Minus schon ab 24 Std. vor dem Spieltag zurückverkaufen (E04.09)",
    "conditional_repayment": "Gewinnspieler sichern ihre eigene Finanzierung ab (E04.04)",
    "upgrade_financing": "Startelf-Upgrade über den Verkauf des Verdrängten finanzieren (E04.05)",
}


def load(raw: object) -> dict[str, str]:
    """The stored flags, every known one with its stage: tolerant, like loading options. Unknown names
    are dropped, junk stages count as off."""
    data = raw if isinstance(raw, dict) else {}
    return {name: data[name] if data.get(name) in STAGES else OFF for name in FLAGS}


def validate(raw: object) -> tuple[dict[str, str] | None, list[dict]]:
    """Strict, for imports and the UI: a dict of known flag names to stages. Missing flags stay as they
    are (the caller merges). Every error with its name, nothing is taken over with an error."""
    if not isinstance(raw, dict):
        return None, [{"path": "flags", "message": "muss ein JSON-Objekt sein"}]
    errors = []
    for name, stage in raw.items():
        if name not in FLAGS:
            errors.append({"path": f"flags.{name}", "message": "unbekanntes Feature Flag"})
        elif stage not in STAGES:
            errors.append({"path": f"flags.{name}", "message": f"erlaubt sind {', '.join(STAGES)}"})
    return (None, errors) if errors else (dict(raw), [])


def effective(flags: dict[str, str], name: str, live_trading: bool) -> str:
    """The stage that really applies: `live` needs the league's live switch, else it is a dry run."""
    stage = flags.get(name, OFF)
    return DRY_RUN if stage == LIVE and not live_trading else stage


def all_effective(flags: dict[str, str], live_trading: bool) -> dict[str, str]:
    return {name: effective(flags, name, live_trading) for name in FLAGS}
