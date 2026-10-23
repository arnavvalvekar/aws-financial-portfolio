"""CrashLab re-pricing engine.

Applies a scenario shock to the frozen decision weights and reports how the
portfolio would hold up. The model is deliberately simple and transparent: each
held name takes the scenario's market shock scaled by its sector beta (plus an
oil overlay for energy when the scenario sets one). That single-beta assumption
is stated on every scenario and in the limitations — CrashLab's value is the
auditable what-if, not a precise crisis simulator.

We reuse Person A's cost model (costs_bps, invested fraction) so the stress sits
on the same basis as the backtest. We do not modify A's engine; we read the same
config and apply the same one-time cost drag.

Public API:
  shock_return(ticker, scenario)      -> the assumed return of one name under a shock
  stress(decision, scenario, config)  -> per-scenario report dict
  run(decision, config, scenarios)    -> list of reports, worst first
"""

from .scenarios import sector_of

CASH = "CASH"


def shock_return(ticker, scenario):
    """Assumed return of one position under a scenario (a negative number for a loss).

    market_shock scaled by the sector beta; energy also takes the oil overlay
    when present. CASH is flat.
    """
    if ticker == CASH:
        return 0.0
    betas = scenario.get("sector_betas", {})
    sector = sector_of(ticker)
    beta = betas.get(sector, 1.0)
    r = scenario["market_shock"] * beta
    if scenario.get("oil_shock") is not None and sector == "energy":
        # Energy producers partly benefit from an oil move; blend the market
        # beta with the direct oil sensitivity (half weight each, documented).
        r = 0.5 * r + 0.5 * (-scenario["oil_shock"])
    return r


def stress(decision, scenario, config):
    """Re-price the frozen weights under one scenario. Returns a report dict.

    Report keys mirror the backtest's metric vocabulary where they apply:
      scenario, label, kind, portfolio_shock (total return under the shock),
      culprits (per-position contribution to the loss, worst first),
      mechanism, assumptions, source.
    """
    weights = dict(decision["weights"])
    cost_bps = float(config.get("costs_bps", 0.0))
    invested = sum(w for t, w in weights.items() if t != CASH and w)
    cost = (cost_bps / 1e4) * invested

    contributions = {}
    for ticker, w in weights.items():
        if not w:
            continue
        r = shock_return(ticker, scenario)
        contributions[ticker] = float(w) * r  # weighted contribution to portfolio return

    portfolio_shock = sum(contributions.values()) - cost
    culprits = sorted(
        ({"ticker": t, "weight": weights[t], "position_return": shock_return(t, scenario),
          "contribution": c} for t, c in contributions.items() if t != CASH and c != 0),
        key=lambda x: x["contribution"],
    )
    report = {
        "scenario": scenario["id"],
        "label": scenario["label"],
        "kind": scenario["kind"],
        "market_shock": scenario["market_shock"],
        "portfolio_shock": round(portfolio_shock, 4),
        "cash_weight": round(weights.get(CASH, 0.0), 4),
        "cost_drag": round(-cost, 4),
        "culprits": [
            {"ticker": c["ticker"], "weight": round(c["weight"], 4),
             "position_return": round(c["position_return"], 4),
             "contribution": round(c["contribution"], 4)}
            for c in culprits[:5]
        ],
        "mechanism": scenario.get("mechanism", ""),
        "assumptions": scenario.get("assumptions", ""),
    }
    if scenario.get("source"):
        report["source"] = scenario["source"]
    if scenario.get("expected_casualties"):
        report["expected_casualties"] = scenario["expected_casualties"]
    return report


def run(decision, config, scenarios):
    """Stress the decision under every scenario; return reports sorted worst-first."""
    reports = [stress(decision, s, config) for s in scenarios]
    reports.sort(key=lambda r: r["portfolio_shock"])  # most negative first
    return reports


__all__ = ["shock_return", "stress", "run", "CASH"]
