"""Checks and deterministic repairs for analyst views and the portfolio manager decision."""

import json
import re

DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def find_late_dates(obj, asof):
    """Dates after the cutoff anywhere in a JSON-able object."""
    return sorted({d for d in DATE_RE.findall(json.dumps(obj)) if d > asof})


def validate_analyst(report, universe, evidence_ids, asof):
    errors = []
    views = report.get("views", [])
    seen = [v.get("ticker") for v in views]
    for t in universe:
        if seen.count(t) != 1:
            errors.append(f"ticker {t} must appear exactly once (found {seen.count(t)})")
    for v in views:
        t = v.get("ticker")
        if not -1 <= v.get("stance", 0) <= 1:
            errors.append(f"{t}: stance outside -1..1")
        if not 0 <= v.get("confidence", 0) <= 1:
            errors.append(f"{t}: confidence outside 0..1")
        unknown = [e for e in v.get("evidence", []) if e not in evidence_ids]
        if unknown:
            errors.append(f"{t}: evidence ids not in the pack: {unknown}")
    late = find_late_dates(report, asof)
    if late:
        errors.append(f"dates after the cutoff {asof}: {late}")
    return errors


def repair_analyst(report, evidence_ids):
    """Drop unknown evidence ids and clamp ranges. Does not touch late dates."""
    for v in report.get("views", []):
        v["evidence"] = [e for e in v.get("evidence", []) if e in evidence_ids]
        v["stance"] = max(-1.0, min(1.0, v.get("stance", 0.0)))
        v["confidence"] = max(0.0, min(1.0, v.get("confidence", 0.0)))
    return report


def validate_decision(decision, universe, max_weight, max_cash, known_ids, asof):
    errors = []
    weights = decision.get("weights", {})
    for t in list(universe) + ["CASH"]:
        if t not in weights:
            errors.append(f"weights missing {t}")
    total = sum(weights.values())
    if abs(total - 1) > 1e-6:
        errors.append(f"weights sum to {total:.6f}, must be 1")
    for t, w in weights.items():
        if w < 0:
            errors.append(f"{t}: negative weight")
        if t != "CASH" and w > max_weight + 1e-9:
            errors.append(f"{t}: weight {w} above the cap {max_weight}")
    if weights.get("CASH", 0) > max_cash + 1e-9:
        errors.append(f"CASH {weights.get('CASH')} above the cap {max_cash}")
    for t, pos in decision.get("positions", {}).items():
        unknown = [s for s in pos.get("sources", []) if s not in known_ids]
        if unknown:
            errors.append(f"{t}: sources not in any evidence pack: {unknown}")
    late = find_late_dates(decision, asof)
    if late:
        errors.append(f"dates after the cutoff {asof}: {late}")
    return errors


def repair_weights(weights, universe, max_weight, max_cash):
    """Clip to the caps and renormalise to exactly 1. Returns (weights, changed)."""
    names = list(universe) + ["CASH"]
    caps = {t: max_weight for t in universe}
    caps["CASH"] = max_cash
    w = {t: max(0.0, float(weights.get(t, 0.0))) for t in names}
    w = {t: min(v, caps[t]) for t, v in w.items()}
    for _ in range(100):
        deficit = 1.0 - sum(w.values())
        if abs(deficit) < 1e-12:
            break
        room = {t: caps[t] - w[t] for t in names if caps[t] - w[t] > 1e-12} if deficit > 0 else \
               {t: w[t] for t in names if w[t] > 1e-12}
        if not room:
            break
        base = sum(w[t] for t in room) or len(room)
        for t in room:
            share = (w[t] / base) if sum(w[t] for t in room) else 1 / len(room)
            step = deficit * share
            w[t] = min(caps[t], max(0.0, w[t] + step))
    w = {t: round(v, 6) for t, v in w.items()}
    drift = round(1.0 - sum(w.values()), 6)
    if drift:
        for t in sorted(names, key=lambda n: -w[n]):
            if 0 <= w[t] + drift <= caps[t]:
                w[t] = round(w[t] + drift, 6)
                break
    changed = any(abs(w[t] - float(weights.get(t, 0.0))) > 1e-9 for t in names)
    return w, changed
