"""Analyst scorecard (Phase 3 stretch): did each analyst's calls pay off?

Joins each analyst's per-ticker ``stance`` (-1..+1, from the analyst packs in
``runs/<id>/analysts/*.json``) against the ticker's REALIZED forward return over
the scored window ``[asof, end]``. Like the backtest, this is post-cutoff
scoring, so it reads later prices DIRECTLY from the price store — NOT through
``src.pit``. It never feeds an agent; it only grades calls after the fact.

Per analyst it reports:
  - n_views            : number of gradable views (non-null stance + return)
  - hit_rate           : fraction where sign(stance) == sign(forward_return),
                         counting only views with a non-trivial stance
  - stance_weighted_ret: mean of stance * forward_return (conviction in the
                         right direction scores positive; wrong direction,
                         negative). The headline "did it pay off" number.
  - rank_ic            : Spearman rank correlation between stance and return
                         (does the analyst rank winners above losers?)
  - avg_abs_stance     : how opinionated the analyst was (context for the above)

A positive ``stance_weighted_ret`` and ``rank_ic`` mean the analyst's directional
calls aligned with what the market did next.

Public API:
    forward_returns(universe, asof, end, store_dir) -> dict[ticker, float]
    score_analyst(views, returns) -> dict          # pure, unit-testable seam
    build_scorecard(run_dir, config, store_dir) -> dict
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

# Reuse the engine's store loader + relative helpers for consistency.
from .engine import load_store, _price_series, _calendar, _relative  # noqa: E402

STANCE_EPS = 0.05  # stances with |stance| <= EPS are "no call" for hit-rate


def forward_returns(
    universe: list[str], asof: str, end: str, store_dir: str | Path = "data/prices"
) -> dict[str, float]:
    """Realized total return per ticker over [asof, end], from adjusted close.

    Post-cutoff scoring: reads the price store directly (not via pit). Uses the
    same SPY trading calendar + normalization as the backtest so returns line up.
    """
    prices = load_store(store_dir)
    asof_ts = pd.Timestamp(asof).normalize()
    end_ts = pd.Timestamp(end).normalize()
    if "SPY" not in prices:
        raise KeyError("price store must contain SPY (the calendar anchor)")
    calendar = _calendar(prices["SPY"], asof_ts, end_ts)

    out: dict[str, float] = {}
    for ticker in universe:
        if ticker not in prices:
            continue
        rel = _relative(_price_series(prices[ticker]), calendar)
        out[ticker] = float(rel.iloc[-1]) - 1.0  # relative starts at 1.0 at asof
    return out


def _spearman(xs: list[float], ys: list[float]) -> float | None:
    """Spearman rank correlation without SciPy. None if undefined (<2 points or
    no variance)."""
    n = len(xs)
    if n < 2:
        return None

    def rank(values: list[float]) -> list[float]:
        order = sorted(range(n), key=lambda i: values[i])
        ranks = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and values[order[j + 1]] == values[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0  # average rank for ties (1-based)
            for k in range(i, j + 1):
                ranks[order[k]] = avg
            i = j + 1
        return ranks

    rx, ry = rank(xs), rank(ys)
    mx = sum(rx) / n
    my = sum(ry) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx = sum((a - mx) ** 2 for a in rx)
    vy = sum((b - my) ** 2 for b in ry)
    if vx == 0 or vy == 0:
        return None
    return cov / (vx * vy) ** 0.5


def score_analyst(
    views: list[dict[str, Any]], returns: dict[str, float]
) -> dict[str, Any]:
    """Grade one analyst's views against realized returns. Pure function."""
    stances: list[float] = []
    rets: list[float] = []
    hits = 0
    calls = 0
    for view in views:
        ticker = view.get("ticker")
        stance = view.get("stance")
        if ticker is None or stance is None or ticker not in returns:
            continue
        try:
            s = float(stance)
        except (TypeError, ValueError):
            continue
        r = returns[ticker]
        stances.append(s)
        rets.append(r)
        if abs(s) > STANCE_EPS:  # only count directional calls in hit rate
            calls += 1
            if (s > 0 and r > 0) or (s < 0 and r < 0):
                hits += 1

    n = len(stances)
    if n == 0:
        return {
            "n_views": 0, "hit_rate": None, "stance_weighted_ret": None,
            "rank_ic": None, "avg_abs_stance": None,
        }
    return {
        "n_views": n,
        "hit_rate": (hits / calls) if calls else None,
        "stance_weighted_ret": sum(s * r for s, r in zip(stances, rets)) / n,
        "rank_ic": _spearman(stances, rets),
        "avg_abs_stance": sum(abs(s) for s in stances) / n,
    }


def _read_analyst_packs(run_dir: Path) -> dict[str, list[dict[str, Any]]]:
    """{analyst_name: [views]} from runs/<id>/analysts/*.json. Skips bad files."""
    analyst_dir = run_dir / "analysts"
    packs: dict[str, list[dict[str, Any]]] = {}
    if not analyst_dir.is_dir():
        return packs
    for path in sorted(analyst_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        name = str(payload.get("analyst", path.stem))
        views = payload.get("views")
        if isinstance(views, list):
            packs[name] = [v for v in views if isinstance(v, dict)]
    return packs


def build_scorecard(
    run_dir: str | Path, config: dict[str, Any], store_dir: str | Path = "data/prices"
) -> dict[str, Any]:
    """Build the full scorecard for a run. Returns a dict safe to JSON-dump.

    Requires analyst packs in the run; returns an empty, flagged scorecard if
    none exist (e.g. a technical-only fallback run)."""
    run_path = Path(run_dir)
    metrics = json.loads((run_path / "metrics.json").read_text())
    asof = metrics.get("asof") or config.get("asof")
    end = metrics.get("end") or config.get("end")
    universe = list(config.get("universe", []))

    packs = _read_analyst_packs(run_path)
    if not packs:
        return {"asof": asof, "end": end, "analysts": {}, "note": "no analyst packs for this run"}

    returns = forward_returns(universe, asof, end, store_dir)
    scores = {name: score_analyst(views, returns) for name, views in packs.items()}
    # Rank analysts by the headline metric when available.
    ranked = sorted(
        (n for n in scores if scores[n]["stance_weighted_ret"] is not None),
        key=lambda n: scores[n]["stance_weighted_ret"],
        reverse=True,
    )
    return {
        "asof": asof, "end": end,
        "forward_returns": returns,
        "analysts": scores,
        "ranking": ranked,
    }


def render_scorecard(scorecard: dict[str, Any]) -> str:
    """Plain-text table for the CLI."""
    analysts = scorecard.get("analysts", {})
    if not analysts:
        return "Analyst scorecard: " + scorecard.get("note", "no data")
    lines = ["Analyst scorecard (did the calls pay off?):"]
    header = f"  {'analyst':14}{'views':>6}{'hit_rate':>10}{'stance*ret':>12}{'rank_ic':>9}"
    lines.append(header)
    lines.append("  " + "-" * (len(header) - 2))
    ranking = scorecard.get("ranking") or list(analysts)
    for name in ranking:
        s = analysts[name]
        def f(v, pct=False):
            if v is None:
                return "—"
            return f"{v*100:.1f}%" if pct else f"{v:+.3f}"
        lines.append(
            f"  {name:14}{s['n_views']:>6}"
            f"{(f(s['hit_rate'], pct=True)):>10}"
            f"{f(s['stance_weighted_ret']):>12}"
            f"{f(s['rank_ic']):>9}"
        )
    return "\n".join(lines)


# Local config loader (mirrors the dashboard/backtest minimal parser; the venv
# has no YAML lib).
def _load_config(path: str | Path) -> dict[str, Any]:
    result: dict[str, Any] = {}
    current: dict[str, Any] | None = None

    def coerce(raw: str) -> Any:
        v = raw.strip()
        if v.startswith("[") and v.endswith("]"):
            inner = v[1:-1].strip()
            return [coerce(x) for x in inner.split(",")] if inner else []
        if v.lower() in ("true", "false"):
            return v.lower() == "true"
        for cast in (int, float):
            try:
                return cast(v)
            except ValueError:
                pass
        return v.strip("'\"")

    for raw_line in Path(path).read_text().splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        indented = line[0] in (" ", "\t")
        key, _, value = line.strip().partition(":")
        key, value = key.strip(), value.strip()
        if indented and current is not None:
            current[key] = coerce(value)
        elif value == "":
            current = {}
            result[key] = current
        else:
            result[key] = coerce(value)
            current = None
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, help="run dir with metrics.json + analysts/")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--store-dir", default="data/prices")
    parser.add_argument("--out", default=None, help="optional path to write scorecard.json")
    args = parser.parse_args(argv)

    config = _load_config(args.config)
    scorecard = build_scorecard(args.run, config, store_dir=args.store_dir)
    print(render_scorecard(scorecard))
    out = args.out or str(Path(args.run) / "scorecard.json")
    Path(out).write_text(json.dumps(scorecard, indent=2))
    print(f"\nWrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
