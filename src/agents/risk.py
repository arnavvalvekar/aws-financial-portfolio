"""Risk review of the portfolio manager's decision. Report-only: it never changes decision.json.

Two layers. Plain-code checks run first and are always reproducible. A model then reads the decision,
the check results, the analyst consensus and a list of past mistakes, and returns approve, adjust or veto.
"""

import json
import os
import re
from pathlib import Path

from .llm import call_json
from .schemas import risk_schema
from .validate import find_late_dates, repair_weights

ROOT = Path(__file__).resolve().parents[2]

SECTORS = {
    "AAPL": "Technology", "MSFT": "Technology", "NVDA": "Technology", "AMZN": "Consumer Discretionary",
    "XOM": "Energy", "JNJ": "Health Care", "PG": "Consumer Staples", "KO": "Consumer Staples",
    "CAT": "Industrials", "NEE": "Utilities",
}
MAX_SECTOR = 0.40
MAX_TOP3 = 0.55
CRASH_SCORE_LIMIT = 0.5   # at or above this, hold at least MIN_CASH_IN_STRESS in cash
MIN_CASH_IN_STRESS = 0.10


def crash_score(regime):
    """Latest crash_risk_score from the regime evidence pack, or None."""
    for item in (regime or {}).get("items", []):
        m = re.search(r"crash_risk_score=([0-9.]+)", item.get("text", ""))
        if m:
            return float(m.group(1))
    return None


def rule_checks(decision, agreement, cfg, regime=None):
    """Deterministic checks. Returns a list of {name, passed, detail}."""
    universe = cfg["universe"]
    c = cfg["constraints"]
    w = decision["weights"]
    eq = 1 / len(universe)
    checks = []

    def add(name, passed, detail=""):
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    over = {t: w[t] for t in universe if w.get(t, 0) > c["max_weight"] + 1e-9}
    add("position_cap", not over, f"above {c['max_weight']:.0%}: {over}" if over else "")
    add("cash_cap", w.get("CASH", 0) <= c["max_cash"] + 1e-9, f"cash {w.get('CASH', 0):.1%}")

    by_sector = {}
    for t in universe:
        by_sector[SECTORS.get(t, "Other")] = by_sector.get(SECTORS.get(t, "Other"), 0) + w.get(t, 0)
    heavy = {s: round(v, 3) for s, v in by_sector.items() if v > MAX_SECTOR}
    add("sector_concentration", not heavy, f"above {MAX_SECTOR:.0%}: {heavy}" if heavy else "")

    top3 = sum(sorted((w.get(t, 0) for t in universe), reverse=True)[:3])
    add("top3_concentration", top3 <= MAX_TOP3, f"top three positions hold {top3:.1%}")

    stances = agreement["by_ticker"]
    against = []
    for t in universe:
        mean = stances.get(t, {}).get("mean_stance", 0)
        if w.get(t, 0) > eq + 0.03 and mean < -0.15:
            against.append(f"{t} overweight ({w[t]:.0%}) with consensus {mean:+.2f}")
        if w.get(t, 0) < eq * 0.5 and mean > 0.4:
            against.append(f"{t} underweight ({w[t]:.0%}) with consensus {mean:+.2f}")
    add("against_consensus", not against, "; ".join(against))

    weak = [t for t in universe if w.get(t, 0) > 0.10 and decision["positions"][t]["confidence"] < 0.5]
    add("confidence_vs_size", not weak, f"large position, low confidence: {weak}" if weak else "")

    unsourced = [t for t in universe if w.get(t, 0) > 0.02 and not decision["positions"][t]["sources"]]
    add("sourced_positions", not unsourced, f"no sources: {unsourced}" if unsourced else "")

    score = crash_score(regime)
    if score is not None:
        stressed = score >= CRASH_SCORE_LIMIT and w.get("CASH", 0) < MIN_CASH_IN_STRESS
        add("regime_vs_cash", not stressed, f"crash risk score {score:.2f}, cash {w.get('CASH', 0):.1%}")
    return checks


def lessons_from_dev_runs(runs_dir=None):
    """Past mistakes of this system, from the warnings of earlier development runs only.

    Only validator warnings are used (bad citations, cap breaches, weights off). No scored result is ever
    read, so a lesson cannot carry information about how the market moved after the cutoff.
    """
    runs = Path(runs_dir or os.getenv("RUNS_DIR", ROOT / "runs"))
    kinds = {
        "not in the pack": "Analysts sometimes cite evidence ids that do not exist. Check every citation.",
        "not in any evidence pack": "The manager sometimes cites sources that are not in any evidence pack.",
        "corrected citation": "Citations sometimes arrive with small typos. Check that sources are real.",
        "above the cap": "The manager sometimes proposes a weight above the per-position cap.",
        "must be 1": "The manager's weights sometimes do not sum to 1.",
        "above the cap ": "Cash sometimes exceeds its cap.",
    }
    seen = {}
    for meta in sorted(runs.glob("dev-*/meta.json")):
        try:
            warnings = json.loads(meta.read_text()).get("warnings", [])
        except (OSError, ValueError):
            continue
        for w in warnings:
            for key, text in kinds.items():
                if key in w:
                    seen[text] = seen.get(text, 0) + 1
                    break
    return [f"{text} (seen {n} time{'s' if n != 1 else ''} in earlier development runs)" for text, n in seen.items()]


def load_lessons():
    """The frozen lessons.json if it exists (so a fresh clone sees the same prompt), else from dev runs."""
    frozen = ROOT / "lessons.json"
    if frozen.exists():
        return json.loads(frozen.read_text())
    return lessons_from_dev_runs()


SYSTEM = """You are the risk manager of a small long-only fund. Today is {asof}. Nothing after that date is known to you.

You review the portfolio manager's proposed weights before they are frozen. You do not pick stocks. You look for mistakes and fragility.

Rules:
- Start from the code checks. A failed check is a concern unless the evidence clearly justifies it.
- Compare the weights with the analyst consensus table. A large position against the consensus needs a reason in the manager's rationale.
- Flag concentration, low-confidence positions that are large, and thin sourcing.
- Consider the lessons list: mistakes this system made before.
- Verdict approve: the weights are acceptable. adjusted_weights must equal the proposed weights.
- Verdict adjust: the weights need small changes. Put the full corrected weights in adjusted_weights (long only, sum to 1, no stock above {max_weight:.0%}, cash at most {max_cash:.0%}).
- Verdict veto: the decision should not be used. Explain why in reasons.
- Every reason is one sentence and names a ticker, a check or an evidence id. Use only the material given."""


def run_risk(decision, agreement, cfg, regime=None, use_cache=True, lessons=None):
    """Returns the risk review dict (see SCHEMAS.md)."""
    universe, asof = cfg["universe"], str(cfg["asof"])
    c = cfg["constraints"]
    checks = rule_checks(decision, agreement, cfg, regime)
    lessons = load_lessons() if lessons is None else lessons
    slim = {t: {"weight": decision["weights"][t], "confidence": p["confidence"], "rationale": p["rationale"],
                "conflicts": p["conflicts"], "change_triggers": p["change_triggers"]}
            for t, p in decision["positions"].items()}
    regime_text = [i["text"] for i in (regime or {}).get("items", []) if i.get("ticker") == "SPY"][:1]
    user = (f"Proposed weights:\n{json.dumps(decision['weights'], indent=1)}\n\n"
            f"Positions:\n{json.dumps(slim, indent=1)}\n\n"
            f"Analyst consensus (mean stance, spread):\n{json.dumps(agreement['by_ticker'], indent=1)}\n\n"
            f"Code checks:\n{json.dumps(checks, indent=1)}\n\n"
            f"Market regime: {regime_text[0] if regime_text else 'not available'}\n\n"
            f"Lessons from earlier development runs:\n{json.dumps(lessons)}\n\nSubmit your review.")
    out = call_json(system=SYSTEM.format(asof=asof, max_weight=c["max_weight"], max_cash=c["max_cash"]),
                    user=user, tool_name="submit_risk_review", schema=risk_schema(universe),
                    model=cfg.get("risk_model", cfg["model"]), region=cfg.get("region", "us-east-1"),
                    use_cache=use_cache)
    late = find_late_dates(out, asof)
    if late:
        raise RuntimeError(f"risk review: look-ahead detected: dates after the cutoff {asof}: {late}")
    adjusted = None
    if out["verdict"] == "adjust":
        adjusted, _ = repair_weights(out["adjusted_weights"], universe, c["max_weight"], c["max_cash"])
    return {"asof": asof, "mode": "report-only", "verdict": out["verdict"], "checks": checks,
            "failed_checks": [k["name"] for k in checks if not k["passed"]],
            "reasons": out["reasons"], "concerns": out["concerns"], "adjusted_weights": adjusted,
            "lessons_used": lessons}
