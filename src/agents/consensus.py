"""Where the analysts agree and disagree, computed in code from their reports (no model call)."""

from math import sqrt


def disagreement(reports):
    """Per ticker: confidence-weighted mean stance, spread (confidence-weighted std) and each stance.

    Analysts with zero confidence (no data) are left out. `most_contested` ranks tickers by spread,
    which is the rule for choosing the deep-dive position in the demo.
    """
    tickers = [v["ticker"] for v in reports[0]["views"]] if reports else []
    by_ticker = {}
    for t in tickers:
        rows = [(r["analyst"], v["stance"], v["confidence"])
                for r in reports for v in r["views"] if v["ticker"] == t]
        active = [x for x in rows if x[2] > 0]
        total = sum(c for _, _, c in active)
        if total == 0:
            by_ticker[t] = {"mean_stance": 0.0, "spread": 0.0, "n_active": 0, "stances": {}}
            continue
        mean = sum(s * c for _, s, c in active) / total
        spread = sqrt(sum(c * (s - mean) ** 2 for _, s, c in active) / total)
        by_ticker[t] = {
            "mean_stance": round(mean, 3),
            "spread": round(spread, 3),
            "n_active": len(active),
            "stances": {a: round(s, 2) for a, s, _ in active},
        }
    ranked = sorted(by_ticker, key=lambda t: -by_ticker[t]["spread"])
    return {"by_ticker": by_ticker, "most_contested": ranked[:3]}
