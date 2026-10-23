"""Protective-change proposals for CrashLab.

From the worst scenario, propose concrete, constraint-respecting adjustments and
report the trade-off: how much shock drawdown the change removes, against how
much base-case return it gives up. Proposals only — any real change still goes
through the portfolio manager and the validator. Nothing here mutates the frozen
decision.

The one base-case number we need (expected return per name over the scored
window) comes from the committed backtest contributions if available, so the
give-up estimate is grounded in the real run rather than invented.
"""

from .engine import CASH, shock_return, stress
from .scenarios import sector_of


def _base_case_returns(decision, metrics):
    """Per-name base-case return over the scored window, from committed contributions.

    contributions are weight*(relative-1)*drag, so dividing by weight recovers
    the name's window return. Falls back to 0 when unavailable (give-up unknown).
    """
    out = {}
    weights = decision.get("weights", {})
    contrib = (metrics or {}).get("contributions", {})
    for t, w in weights.items():
        if t in (CASH,) or not w:
            continue
        c = contrib.get(t)
        out[t] = (c / w) if (c is not None and w) else 0.0
    return out


def propose(decision, worst_scenario, config, metrics=None, max_moves=3):
    """Propose protective changes against the worst scenario.

    Returns a list of proposals, each with the change, the shock drawdown it
    removes, and the base-case return it gives up. Respects long-only, the
    per-name cap and the cash cap from config constraints.
    """
    c = config.get("constraints", {})
    max_cash = float(c.get("max_cash", 0.20))
    weights = dict(decision["weights"])
    base = _base_case_returns(decision, metrics)

    baseline = stress(decision, worst_scenario, config)["portfolio_shock"]
    proposals = []

    # Rank held names by how much they hurt in the worst scenario.
    culprits = sorted(
        ((t, w) for t, w in weights.items() if t != CASH and w),
        key=lambda tw: weights[tw[0]] * shock_return(tw[0], worst_scenario),
    )

    cash_room = max(0.0, max_cash - weights.get(CASH, 0.0))
    for ticker, w in culprits[:max_moves]:
        if cash_room <= 0:
            break
        # Trim this name by up to half its weight, parked in cash (within the cap).
        trim = min(w * 0.5, cash_room)
        if trim <= 1e-6:
            continue
        trial = dict(weights)
        trial[ticker] = round(w - trim, 4)
        trial[CASH] = round(trial.get(CASH, 0.0) + trim, 4)
        trial_shock = stress({"weights": trial}, worst_scenario, config)["portfolio_shock"]

        drawdown_removed = trial_shock - baseline              # positive = less bad
        base_give_up = trim * base.get(ticker, 0.0)            # return forgone in base case
        proposals.append({
            "change": f"Trim {ticker} by {trim:.0%} into CASH "
                      f"({w:.0%} -> {trial[ticker]:.0%}; CASH -> {trial[CASH]:.0%})",
            "ticker": ticker,
            "trim": round(trim, 4),
            "shock_drawdown_removed": round(drawdown_removed, 4),
            "base_case_return_given_up": round(base_give_up, 4),
            "sector": sector_of(ticker),
            "note": "Proposal only; goes through the manager and validator. "
                    "Respects long-only, 25% name cap and 20% cash cap.",
        })
        cash_room -= trim

    # Rank proposals by protection per unit of give-up (most efficient first).
    proposals.sort(key=lambda p: -(p["shock_drawdown_removed"]
                                   / (abs(p["base_case_return_given_up"]) + 1e-9)))
    return {
        "worst_scenario": worst_scenario["id"],
        "baseline_shock": round(baseline, 4),
        "proposals": proposals,
        "disclaimer": "CrashLab proposals are a separate, clearly-labelled variant. "
                      "The frozen decision.json is unchanged.",
    }


__all__ = ["propose"]
