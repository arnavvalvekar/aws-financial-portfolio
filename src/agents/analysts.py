"""The five specialist analysts. Each reads one evidence pack and returns one view per ticker."""

import json

from .llm import call_json
from .schemas import ANALYSTS, analyst_schema
from .validate import repair_analyst, validate_analyst

FOCUS = {
    "technical": "price momentum, volatility, drawdown and trend against the 50 and 200-day averages",
    "fundamentals": "revenue and profit growth, margins, leverage, cash generation and return on equity from SEC filings",
    "macro": "interest rates, the yield curve, inflation, unemployment, oil and market volatility, and how they affect each company",
    "sentiment": "media tone and market fear gauges, and whether sentiment is stretched or washed out for each company",
    "geopolitics": "trade, sanctions, conflict and policy events, and each company's exposure to them",
}

SYSTEM = """You are the {name} analyst on a small investment team. You advise a portfolio manager who builds a long-only portfolio of {n} US stocks. Today is {asof}. Nothing after that date is known to you.

Rules:
- Use only the evidence items provided. Do not use outside knowledge of any event, price or filing dated after {asof}.
- Cite the id of every evidence item a view rests on, copied exactly as written.
- Give exactly one view per ticker. If the evidence for a ticker is thin, set stance 0 and confidence 0 and write "insufficient data" in the thesis.
- stance runs from -1 (strong underweight) to +1 (strong overweight). confidence runs from 0 to 1.
- change_triggers name the observable condition that would flip or weaken the view.
- Keep each thesis to one or two sentences.

Your focus: {focus}."""


def run_analyst(name, pack, cfg, use_cache=True):
    """Run one analyst. Returns (report, warnings). Raises if a date after the cutoff survives a retry."""
    universe, asof = cfg["universe"], str(cfg["asof"])
    ids = {item["id"] for item in pack["items"]}
    system = SYSTEM.format(name=name, n=len(universe), asof=asof, focus=FOCUS[name])
    user = (f"Universe: {', '.join(universe)}\n\nEvidence items (id, ticker, date, text):\n"
            f"{json.dumps(pack['items'], indent=1)}\n\nSubmit one view for each ticker.")
    schema = analyst_schema(universe)

    def ask(prompt):
        return call_json(system=system, user=prompt, tool_name=f"submit_{name}_views", schema=schema,
                         model=cfg["model"], region=cfg.get("region", "us-east-1"), use_cache=use_cache)

    report = ask(user)
    errors = validate_analyst(report, universe, ids, asof)
    warnings = []
    if errors:
        report = ask(user + "\n\nYour previous answer had these problems. Fix them:\n- " + "\n- ".join(errors))
        errors = validate_analyst(report, universe, ids, asof)
    if any("after the cutoff" in e for e in errors):
        raise RuntimeError(f"{name}: look-ahead detected after a retry: {errors}")
    if errors:
        warnings = [f"{name}: repaired after retry: {e}" for e in errors]
        report = repair_analyst(report, ids)
    return {"analyst": name, "asof": asof, **report}, warnings


__all__ = ["ANALYSTS", "run_analyst"]
