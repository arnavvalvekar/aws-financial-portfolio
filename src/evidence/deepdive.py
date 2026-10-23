"""Deep-dive position rule (owner C).

The demo opens one decision in detail. The rule, fixed before any result is
looked at, is: the position with the largest analyst disagreement, measured by
the confidence-weighted stance spread that src/agents/consensus.py already
computes per run into disagreement.json. Picking by disagreement (not by which
analyst "won", and not by return) keeps the choice honest and reproducible.

This module only selects and explains; it computes nothing new. It reads the
run's disagreement.json (B's artifact) and, optionally, decision.json to attach
the chosen weight and rationale for the demo narration.

Public API:
  pick(run_dir)            -> dict describing the deep-dive position, or None
  rule_text()              -> the one-line rule, for the README / dashboard
"""

import json
from pathlib import Path

RULE = ("Deep-dive = the position with the largest analyst disagreement "
        "(highest confidence-weighted stance spread), chosen by rule before any "
        "result is seen.")


def rule_text():
    return RULE


def _load(path):
    p = Path(path)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def pick(run_dir):
    """Choose the deep-dive ticker for a completed run.

    Reads <run_dir>/disagreement.json for the ranking. Returns a dict:
      {ticker, spread, mean_stance, stances, weight, rationale, conflicts, rule}
    or None if the disagreement artifact is missing/empty. Ties break by the
    ranking consensus.py already produced (most_contested order), so the pick
    is deterministic.
    """
    run = Path(run_dir)
    dis = _load(run / "disagreement.json")
    if not dis:
        return None
    by_ticker = dis.get("by_ticker", {})
    ranked = dis.get("most_contested") or sorted(
        by_ticker, key=lambda t: -by_ticker.get(t, {}).get("spread", 0.0))
    if not ranked:
        return None
    ticker = ranked[0]
    stats = by_ticker.get(ticker, {})

    out = {
        "ticker": ticker,
        "spread": stats.get("spread"),
        "mean_stance": stats.get("mean_stance"),
        "stances": stats.get("stances", {}),
        "rule": RULE,
    }

    # Attach the manager's take on that position, if the decision is present.
    decision = _load(run / "decision.json")
    if decision:
        weights = decision.get("weights", {})
        pos = (decision.get("positions") or {}).get(ticker, {})
        out["weight"] = weights.get(ticker)
        out["rationale"] = pos.get("rationale")
        out["conflicts"] = pos.get("conflicts")
        out["sources"] = pos.get("sources")
        out["change_triggers"] = pos.get("change_triggers")
    return out


def write(run_dir):
    """Write <run_dir>/deepdive.json and return the pick (or None)."""
    chosen = pick(run_dir)
    if chosen is not None:
        (Path(run_dir) / "deepdive.json").write_text(json.dumps(chosen, indent=2))
    return chosen


__all__ = ["pick", "write", "rule_text", "RULE"]
