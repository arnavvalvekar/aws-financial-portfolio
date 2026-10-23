"""Live leak attack: try to sneak the future into the pipeline and watch each guard refuse.

    python demo_leak_attack.py            # runs all attacks and prints what each guard said
    python demo_leak_attack.py --pause    # waits for Enter between attacks, for live narration

Offline: no AWS calls and no model calls. The messages shown are the real errors raised by the real
code, not text written for the demo. If an attack is NOT blocked the script says so and exits 1.
"""

import argparse
import copy
import json
import sys
import tempfile
from pathlib import Path

import yaml

from src import pit
from src.agents import analysts
from src.agents.orchestrate import load_evidence

ROOT = Path(__file__).resolve().parent
RED, GREEN, DIM, BOLD, END = "\033[31m", "\033[32m", "\033[2m", "\033[1m", "\033[0m"
FUTURE = "2026-03-02"  # a Monday, five weeks after the cutoff


def _cfg():
    return yaml.safe_load((ROOT / "config.yaml").read_text())


def attack_poisoned_evidence(cfg):
    """A data file contains one item dated after the cutoff."""
    asof = str(cfg["asof"])
    pack = json.loads((ROOT / "evidence" / "technical.json").read_text())
    pack["items"].append({"id": f"px:NVDA:{FUTURE}", "ticker": "NVDA", "date": FUTURE,
                          "text": "NVDA closed at a record high after blowout earnings."})
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "technical.json").write_text(json.dumps(pack))
        try:
            load_evidence(tmp, asof, only=["technical"])
        except Exception as exc:  # noqa: BLE001 - the point is to show whatever the guard says
            return True, f"{type(exc).__name__}: {exc}"
    return False, "the poisoned file was loaded"


def attack_future_prices(cfg):
    """The price store holds prices from after the cutoff. Can an agent read them?"""
    asof = str(cfg["asof"])
    everything = pit.load_prices(ROOT / "data" / "prices")
    through_the_door = pit.slice(everything, asof)
    latest_all, latest_door = everything["date"].max().date(), through_the_door["date"].max().date()
    note = f"the store reaches {latest_all}, but the only door returns rows up to {latest_door}"
    try:  # and if a bug ever let a later row through, the guard raises
        pit._assert_no_future(everything, pit._to_timestamp(asof))
    except ValueError as exc:
        headline = str(exc).split(": [")[0]  # the real error, without the long list of dates
        return latest_door <= pit._to_timestamp(asof).date(), f"{note}. If a later row ever got through: {headline}"
    return False, "later rows were not detected"


def _run_with_fake_model(cfg, views):
    """Run the real technical analyst code with a stand-in model that returns `views`."""
    pack = json.loads((ROOT / "evidence" / "technical.json").read_text())
    real = analysts.call_json
    analysts.call_json = lambda **_: copy.deepcopy(views)
    try:
        return analysts.run_analyst("technical", pack, cfg, use_cache=False)
    finally:
        analysts.call_json = real


def _views(cfg, thesis, evidence):
    return {"views": [{"ticker": t, "stance": 0.5, "confidence": 0.8, "thesis": thesis,
                       "evidence": evidence(t), "change_triggers": ["none"]} for t in cfg["universe"]]}


def attack_model_remembers_the_future(cfg):
    """The model writes a thesis that mentions a date after the cutoff, even when asked to fix it."""
    views = _views(cfg, f"Shares jumped on {FUTURE} after earnings.", lambda t: [f"px:{t}:{cfg['asof']}"])
    try:
        _run_with_fake_model(cfg, views)
    except Exception as exc:  # noqa: BLE001
        return True, f"{type(exc).__name__}: {exc}"[:260]
    return False, "the future date was accepted"


def attack_invented_citation(cfg):
    """The model cites evidence that does not exist."""
    views = _views(cfg, "Looks strong.", lambda t: [f"sec:{t}:10-Q:2025-09-30:MadeUpRevenue"])
    report, warnings = _run_with_fake_model(cfg, views)
    kept = sum(len(v["evidence"]) for v in report["views"])
    return kept == 0, f"{len(warnings)} warnings, invented citations kept: {kept}. First: {warnings[0][:150]}"


ATTACKS = [
    ("Sneak a future price into the evidence", attack_poisoned_evidence),
    ("Read the price store directly, past the cutoff", attack_future_prices),
    ("Make the model write about the future", attack_model_remembers_the_future),
    ("Make the model cite evidence that does not exist", attack_invented_citation),
]


def run_attacks(cfg=None):
    cfg = cfg or _cfg()
    return [(title, *fn(cfg)) for title, fn in ATTACKS]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--pause", action="store_true", help="wait for Enter between attacks")
    a = p.parse_args()
    cfg = _cfg()
    print(f"{BOLD}Cutoff: {cfg['asof']}. Nothing dated after this day may reach an agent.{END}\n")
    blocked = 0
    for n, (title, fn) in enumerate(ATTACKS, 1):
        if a.pause:
            input(f"{DIM}[Enter] for attack {n}{END}")
        print(f"{RED}ATTACK {n}: {title}{END}")
        ok, message = fn(cfg)
        blocked += ok
        print(f"  {GREEN + 'BLOCKED' if ok else RED + 'NOT BLOCKED'}{END}  {message}\n")
    print(f"{BOLD}{blocked} of {len(ATTACKS)} attacks blocked.{END}")
    sys.exit(0 if blocked == len(ATTACKS) else 1)


if __name__ == "__main__":
    main()
