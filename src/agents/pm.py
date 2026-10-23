"""The portfolio manager: reconciles the analysts into target weights with a rationale per position."""

import json

from .llm import call_json
from .schemas import pm_schema
from .validate import repair_weights, validate_decision

SYSTEM = """You are the portfolio manager of a small long-only fund. Today is {asof}. Nothing after that date is known to you.

You receive reports from {analysts} analysts. Turn them into target weights for {n} stocks plus CASH.

Rules:
- Weights sum to 1. Long only. No stock above {max_weight:.0%}. CASH at most {max_cash:.0%}.
- Weigh the analysts by the quality of their evidence and their confidence, not by a fixed formula. Where they disagree, say so in conflicts and explain how you resolved it.
- For each stock, analyst_weighting says how much each analyst influenced that position. The numbers sum to 1.
- sources lists the evidence ids the position rests on. Copy ids only from the analyst reports. Never invent an id.
- change_triggers are the observable conditions that would make you cut or add to the position.
- Use only the reports provided. Do not use outside knowledge of any event dated after {asof}.
- regime_view is your read of the overall market conditions in one or two sentences. portfolio_thesis is one paragraph."""


def run_pm(reports, known_ids, cfg, use_cache=True, agreement=None):
    """Returns (decision, warnings). `agreement` is the code-computed analyst consensus table."""
    universe, asof = cfg["universe"], str(cfg["asof"])
    c = cfg["constraints"]
    analysts = [r["analyst"] for r in reports]
    system = SYSTEM.format(asof=asof, analysts=len(analysts), n=len(universe),
                           max_weight=c["max_weight"], max_cash=c["max_cash"])
    table = ""
    if agreement:
        table = ("Analyst agreement, computed in code (spread is the confidence-weighted standard deviation "
                 "of stances; a high spread means the analysts disagree):\n"
                 f"{json.dumps(agreement['by_ticker'], indent=1)}\n\n")
    user = (f"Universe: {', '.join(universe)}\n\nAnalyst reports:\n{json.dumps(reports, indent=1)}\n\n"
            f"{table}Submit the portfolio decision.")
    schema = pm_schema(universe, analysts)

    def ask(prompt):
        return call_json(system=system, user=prompt, tool_name="submit_decision", schema=schema,
                         model=cfg["model"], region=cfg.get("region", "us-east-1"), use_cache=use_cache)

    def check(d):
        return validate_decision(d, universe, c["max_weight"], c["max_cash"], known_ids, asof)

    decision = ask(user)
    errors = check(decision)
    warnings = []
    if errors:
        decision = ask(user + "\n\nYour previous answer had these problems. Fix them:\n- " + "\n- ".join(errors))
        errors = check(decision)
    if any("after the cutoff" in e for e in errors):
        raise RuntimeError(f"portfolio manager: look-ahead detected after a retry: {errors}")
    if errors:
        warnings = [f"portfolio manager: repaired after retry: {e}" for e in errors]
        decision["weights"], _ = repair_weights(decision["weights"], universe, c["max_weight"], c["max_cash"])
        for pos in decision["positions"].values():
            pos["sources"] = [s for s in pos.get("sources", []) if s in known_ids]
    return {"asof": asof, **decision}, warnings
