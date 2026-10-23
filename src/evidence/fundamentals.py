"""Fundamentals evidence pack from SEC XBRL filings (owner C).

Turns the raw companyfacts blob into a point-in-time evidence pack the
fundamentals analyst can read. Everything is gated on the SEC `filed` date:
only facts whose filing was public on or before the cutoff (`asof`) are used,
so no later restatement or amendment can leak in.

Produces, per ticker:
  - a short line per metric with the value, period and filing date
  - a few derived reads (YoY revenue growth, margins, leverage, ROE) built
    only from pre-cutoff facts

Evidence IDs follow SCHEMAS.md:  sec:<TICKER>:<form>:<period-end>:<tag>

Public API:
  build_pack(universe, asof)        -> evidence pack dict (schema in SCHEMAS.md)
  write_pack(path, universe, asof)  -> write the pack to a JSON file
  facts_table(ticker, asof)         -> per-metric point-in-time facts (for the CSV)
"""

import json
from pathlib import Path

from ..data.sec import company_concept, company_facts

ROOT = Path(__file__).resolve().parents[2]

# Candidate XBRL tags per metric, best first. Grounded in what AAPL/XOM/CAT/etc
# actually report. Among the candidates present, we pick the one whose latest
# pre-cutoff fact has the most recent period end (companies migrate tags over
# time). A metric with no populated candidate is omitted, which the analyst
# reads as thin data.
# NOTE: we deliberately do NOT fall back Liabilities -> LiabilitiesAndStockholdersEquity;
# the latter equals total assets and would be wrong.
METRICS = {
    "Revenues": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "SalesRevenueNet",
    ],
    "GrossProfit": ["GrossProfit"],
    "OperatingIncomeLoss": ["OperatingIncomeLoss"],
    "NetIncomeLoss": ["NetIncomeLoss", "ProfitLoss"],
    "Assets": ["Assets"],
    "Liabilities": ["Liabilities"],
    "StockholdersEquity": [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ],
    "NetCashProvidedByUsedInOperatingActivities": [
        "NetCashProvidedByUsedInOperatingActivities",
    ],
    "LongTermDebt": ["LongTermDebtNoncurrent", "LongTermDebt"],
    "CashAndCashEquivalentsAtCarryingValue": ["CashAndCashEquivalentsAtCarryingValue"],
}

# Which metrics are flow (income-statement / cash-flow, have a period) vs
# stock (balance-sheet, a single instant). Flow facts have start+end; stock
# facts have only end. We pick quarterly-or-annual flow and the latest stock.
FLOW = {
    "Revenues",
    "GrossProfit",
    "OperatingIncomeLoss",
    "NetIncomeLoss",
    "NetCashProvidedByUsedInOperatingActivities",
}


def _usd_units(gaap, tag):
    node = gaap.get(tag)
    if not node:
        return []
    units = node.get("units", {})
    # Almost everything we want is USD; a couple of tags use USD-like variants.
    for key in ("USD",):
        if key in units:
            return units[key]
    return []


def _entries_for(ticker, gaap, tag, asof):
    """All USD entries for a tag, preferring companyfacts but falling back to the
    per-concept endpoint when the aggregate has nothing visible at the cutoff.

    Some large filers (XOM) have a thin or stale companyfacts blob while the
    companyconcept endpoint carries the full history. We only pay for the extra
    request when the aggregate is missing pre-cutoff data for a tag we want.
    """
    entries = _usd_units(gaap, tag)
    if any(str(e.get("filed", "")) <= asof for e in entries):
        return entries
    concept = company_concept(ticker, tag)
    if concept:
        return concept
    return entries


def _visible(entries, asof):
    """Facts whose filing was public on or before the cutoff."""
    return [e for e in entries if str(e.get("filed", "")) <= asof]


def _pick_flow(entries, asof, annual=False):
    """Latest flow fact visible at asof. annual=True prefers ~yearly periods, else ~quarterly."""
    vis = _visible(entries, asof)
    cand = []
    for e in vis:
        start, end = e.get("start"), e.get("end")
        if not start or not end:
            continue
        days = (_date(end) - _date(start)).days
        is_annual = days >= 300
        is_quarter = 80 <= days <= 100
        if annual and is_annual:
            cand.append(e)
        elif not annual and is_quarter:
            cand.append(e)
    if not cand:
        return None
    # latest by period end, then by filing date
    return max(cand, key=lambda e: (e["end"], e.get("filed", "")))


def _pick_stock(entries, asof):
    """Latest balance-sheet fact visible at asof."""
    vis = [e for e in _visible(entries, asof) if e.get("end")]
    if not vis:
        return None
    return max(vis, key=lambda e: (e["end"], e.get("filed", "")))


def _date(s):
    import datetime

    return datetime.date.fromisoformat(str(s))


def _resolve(ticker, gaap, metric, asof, annual=False):
    """Return (tag, fact) for the candidate tag with the most recent usable fact.

    Companies migrate between tags over time (e.g. XOM dropped
    RevenueFromContractWithCustomerExcludingAssessedTax for Revenues after 2023).
    Picking the first tag that merely has *some* fact can lock onto a stale tag,
    so we score every candidate and keep the one whose fact has the latest
    period end (filing date breaks ties).
    """
    best = None  # (period_end, filed, tag, fact)
    for tag in METRICS[metric]:
        entries = _entries_for(ticker, gaap, tag, asof)
        if not entries:
            continue
        fact = _pick_flow(entries, asof, annual) if metric in FLOW else _pick_stock(entries, asof)
        if not fact:
            continue
        key = (fact["end"], fact.get("filed", ""))
        if best is None or key > best[:2]:
            best = (fact["end"], fact.get("filed", ""), tag, fact)
    if best is None:
        return None, None
    return best[2], best[3]


def _prior_year_flow(ticker, gaap, tag, fact, asof, annual=False):
    """The same-tag flow fact one year earlier than `fact`, for YoY growth. Must also be pre-cutoff."""
    entries = _entries_for(ticker, gaap, tag, asof)
    target_end = _date(fact["end"])
    want_low = target_end.replace(year=target_end.year - 1).isoformat()
    best = None
    for e in _visible(entries, asof):
        start, end = e.get("start"), e.get("end")
        if not start or not end:
            continue
        days = (_date(end) - _date(start)).days
        if annual and days < 300:
            continue
        if not annual and not (80 <= days <= 100):
            continue
        # period end roughly one year before the current one
        if abs((_date(end) - _date(want_low)).days) <= 20:
            if best is None or e["end"] > best["end"]:
                best = e
    return best


def _fmt(v):
    """Human-readable money."""
    a = abs(v)
    if a >= 1e9:
        return f"{v / 1e9:.2f}B"
    if a >= 1e6:
        return f"{v / 1e6:.2f}M"
    return f"{v:,.0f}"


def facts_table(ticker, asof, annual=False):
    """Point-in-time metric facts for one ticker: {metric: {tag, val, period_end, form, filed}}.

    Facts whose period end is far older than the cutoff are dropped. A company
    that abandoned a tag years ago (e.g. XOM's LongTermDebtNoncurrent, last filed
    for FY2017) would otherwise surface a stale value as if it were current.
    """
    import datetime

    gaap = company_facts(ticker)["facts"].get("us-gaap", {})
    asof_date = datetime.date.fromisoformat(str(asof))
    # Allow up to ~15 months so an annual-only balance-sheet gap still passes,
    # but a multi-year-old abandoned tag does not.
    oldest_ok = asof_date - datetime.timedelta(days=460)
    out = {}
    for metric in METRICS:
        tag, fact = _resolve(ticker, gaap, metric, asof, annual)
        if not fact:
            continue
        if _date(fact["end"]) < oldest_ok:
            continue  # stale: tag likely abandoned, don't present it as current
        rec = {
            "tag": tag,
            "val": fact["val"],
            "period_end": fact["end"],
            "form": fact.get("form", ""),
            "filed": fact.get("filed", ""),
        }
        if metric in FLOW:
            prior = _prior_year_flow(ticker, gaap, tag, fact, asof, annual)
            if prior and prior["val"]:
                rec["yoy"] = (fact["val"] - prior["val"]) / abs(prior["val"])
        out[metric] = rec
    return out


def _item(ticker, rec, text):
    """An evidence item with an ID per SCHEMAS.md. `date` is the filing date (when public)."""
    eid = f"sec:{ticker}:{rec['form']}:{rec['period_end']}:{rec['tag']}"
    return {"id": eid, "ticker": ticker, "date": rec["filed"], "text": text}


def _ticker_items(ticker, asof, annual=False):
    """Evidence items for one ticker: raw metric lines plus derived reads."""
    table = facts_table(ticker, asof, annual)
    items = []
    if not table:
        return items

    period = "fiscal year" if annual else "quarter"
    for metric, rec in table.items():
        label = metric
        if metric in FLOW:
            when = f"for the {period} ended {rec['period_end']}"
        else:
            when = f"as of {rec['period_end']}"
        txt = f"{label} {when}: {_fmt(rec['val'])} ({rec['form']} filed {rec['filed']})."
        if "yoy" in rec:
            txt += f" Year on year {rec['yoy'] * 100:+.1f}%."
        items.append(_item(ticker, rec, txt))

    # Derived reads, each cites the facts it rests on via its own evidence IDs.
    rev = table.get("Revenues")
    ni = table.get("NetIncomeLoss")
    op = table.get("OperatingIncomeLoss")
    gp = table.get("GrossProfit")
    eq = table.get("StockholdersEquity")
    assets = table.get("Assets")
    liab = table.get("Liabilities")
    ltd = table.get("LongTermDebt")

    def add(rec, txt):
        items.append(_item(ticker, rec, txt))

    def same_period(a, b):
        return a and b and a.get("period_end") == b.get("period_end")

    # Margins only when numerator and revenue cover the same period, so the
    # ratio is not mixing a Q3 flow with an annual one.
    if rev and rev["val"]:
        if same_period(op, rev):
            add(op, f"Operating margin {op['val'] / rev['val'] * 100:.1f}% (operating income over revenue, period ended {op['period_end']}).")
        if same_period(ni, rev):
            add(ni, f"Net margin {ni['val'] / rev['val'] * 100:.1f}% (net income over revenue, period ended {ni['period_end']}).")
        if same_period(gp, rev):
            add(gp, f"Gross margin {gp['val'] / rev['val'] * 100:.1f}% (period ended {gp['period_end']}).")
    if ni and eq and eq["val"]:
        # Single-period net income over equity; labelled plainly as a period ROE.
        add(eq, f"Return on equity {ni['val'] / eq['val'] * 100:.1f}% (net income over shareholders' equity, as of {eq['period_end']}).")
    if liab and eq and eq["val"] and same_period(liab, eq):
        add(eq, f"Leverage: total liabilities / equity {liab['val'] / eq['val']:.2f}x (as of {eq['period_end']}).")
    if ltd and assets and assets["val"] and same_period(ltd, assets):
        add(assets, f"Long-term debt is {ltd['val'] / assets['val'] * 100:.1f}% of total assets (as of {assets['period_end']}).")

    return items


def build_pack(universe, asof, annual=False):
    """Build the fundamentals evidence pack dict. Nothing is dated after asof by construction."""
    asof = str(asof)
    items = []
    covered = []
    for ticker in universe:
        tk_items = _ticker_items(ticker, asof, annual)
        items.extend(tk_items)
        if tk_items:
            covered.append(ticker)

    horizon = max((i["date"] for i in items), default=None)
    missing = [t for t in universe if t not in covered]
    pack = {
        "analyst": "fundamentals",
        "asof": asof,
        "data_horizon": {"sec": horizon},
        "items": items,
    }
    if missing:
        pack["missing_tickers"] = missing
    return pack


def write_pack(path, universe, asof, annual=False):
    pack = build_pack(universe, asof, annual)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(pack, indent=2))
    return pack


def write_csv(path, universe, asof, annual=False):
    """Write a flat fundamentals CSV: one row per ticker/metric with its filing date.

    This is the human-auditable companion to the evidence pack. Columns:
    ticker, metric, tag, value, period_end, form, filed, yoy, evidence_id.
    """
    import csv

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    cols = ["ticker", "metric", "tag", "value", "period_end", "form", "filed", "yoy", "evidence_id"]
    rows = []
    for ticker in universe:
        table = facts_table(ticker, asof, annual)
        for metric, rec in table.items():
            eid = f"sec:{ticker}:{rec['form']}:{rec['period_end']}:{rec['tag']}"
            rows.append({
                "ticker": ticker,
                "metric": metric,
                "tag": rec["tag"],
                "value": rec["val"],
                "period_end": rec["period_end"],
                "form": rec["form"],
                "filed": rec["filed"],
                "yoy": f"{rec['yoy']:.4f}" if "yoy" in rec else "",
                "evidence_id": eid,
            })
    with p.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    return len(rows)


def _main(argv=None):
    import argparse

    import yaml

    ap = argparse.ArgumentParser(description="Build the fundamentals evidence pack and CSV from SEC filings.")
    ap.add_argument("--config", default=str(ROOT / "config.yaml"))
    ap.add_argument("--out", default=str(ROOT / "data" / "fundamentals.json"),
                    help="evidence pack JSON path")
    ap.add_argument("--csv", default=str(ROOT / "data" / "fundamentals.csv"),
                    help="flat CSV path")
    ap.add_argument("--annual", action="store_true", help="use annual (10-K) periods instead of quarterly")
    args = ap.parse_args(argv)

    cfg = yaml.safe_load(Path(args.config).read_text())
    universe, asof = cfg["universe"], str(cfg["asof"])
    pack = write_pack(args.out, universe, asof, args.annual)
    n_rows = write_csv(args.csv, universe, asof, args.annual)

    late = [i["id"] for i in pack["items"] if str(i["date"]) > asof]
    covered = sorted({i["ticker"] for i in pack["items"]})
    print(f"cutoff {asof}")
    print(f"evidence items: {len(pack['items'])}  (csv rows: {n_rows})")
    print(f"data horizon (sec): {pack['data_horizon']['sec']}")
    print(f"tickers covered: {len(covered)}/{len(universe)}")
    if pack.get("missing_tickers"):
        print(f"MISSING: {pack['missing_tickers']}")
    print(f"look-ahead violations: {len(late)} (must be 0)")
    print(f"wrote {args.out}")
    print(f"wrote {args.csv}")
    if late:
        raise SystemExit("look-ahead detected")


__all__ = ["build_pack", "write_pack", "write_csv", "facts_table", "METRICS"]

if __name__ == "__main__":
    _main()
