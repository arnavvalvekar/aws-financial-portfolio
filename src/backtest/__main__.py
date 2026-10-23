"""Backtest CLI (T7, contract C5).

The "one command": score a frozen decision against the price store and print a
plain-text 3-column metrics table for portfolio / SPY / equal_weight, then write
``runs/<run_id>/equity.csv`` and ``runs/<run_id>/metrics.json``.

    python -m src.backtest --config config.yaml --decision runs/<id>/decision.json

Options:
    --store-dir  price store directory (default: data/prices; tests point it at
                 the fixture store).
    --run-id     output folder under runs/ (default: dev-<asof>).
    --rf         risk-free rate for Sharpe (default: 0.0, v1).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .engine import load_store, run_backtest

METRIC_ROWS = [
    ("Total return", "total_return", "pct"),
    ("CAGR", "cagr", "pct"),
    ("Volatility", "volatility", "pct"),
    ("Sharpe", "sharpe", "num"),
    ("Max drawdown", "max_drawdown", "pct"),
    ("  peak date", "max_drawdown_peak", "date"),
    ("  trough date", "max_drawdown_trough", "date"),
]
COLUMNS = ["portfolio", "SPY", "equal_weight"]


# --------------------------------------------------------------------------- #
# Config loading (small, local — mirrors tests/conftest.py; PyYAML if present) #
# --------------------------------------------------------------------------- #
def load_config(path: str | Path) -> dict:
    p = Path(path)
    try:
        import yaml  # type: ignore

        with p.open() as fh:
            return yaml.safe_load(fh)
    except ModuleNotFoundError:
        return _parse_config_minimal(p)


def _coerce(raw: str):
    s = raw.strip()
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        return [_coerce(x) for x in inner.split(",")] if inner else []
    if s.lower() in ("true", "false"):
        return s.lower() == "true"
    for cast in (int, float):
        try:
            return cast(s)
        except ValueError:
            pass
    return s.strip("'\"")


def _parse_config_minimal(path: Path) -> dict:
    result: dict = {}
    current_map: dict | None = None
    with path.open() as fh:
        for raw_line in fh:
            line = raw_line.split("#", 1)[0].rstrip() if "#" in raw_line else raw_line.rstrip()
            if not line.strip():
                continue
            indented = line[0] in (" ", "\t")
            key, _, value = line.strip().partition(":")
            key, value = key.strip(), value.strip()
            if indented and current_map is not None:
                current_map[key] = _coerce(value)
            elif value == "":
                current_map = {}
                result[key] = current_map
            else:
                result[key] = _coerce(value)
                current_map = None
    return result


# --------------------------------------------------------------------------- #
# Formatting                                                                  #
# --------------------------------------------------------------------------- #
def _fmt(value: Any, kind: str) -> str:
    if value is None:
        return "-"
    if kind == "pct":
        return f"{value * 100:.2f}%"
    if kind == "num":
        return f"{value:.3f}"
    return str(value)


def render_table(metrics: dict[str, dict[str, Any]]) -> str:
    label_w = max(len(label) for label, _, _ in METRIC_ROWS) + 2
    col_w = 16
    header = "Metric".ljust(label_w) + "".join(c.rjust(col_w) for c in COLUMNS)
    sep = "-" * len(header)
    lines = [header, sep]
    for label, key, kind in METRIC_ROWS:
        row = label.ljust(label_w)
        for col in COLUMNS:
            row += _fmt(metrics[col].get(key), kind).rjust(col_w)
        lines.append(row)
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Entry point                                                                 #
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.backtest", description=__doc__)
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--decision", required=True)
    parser.add_argument("--store-dir", default="data/prices")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--runs-dir", default="runs")
    parser.add_argument("--rf", type=float, default=0.0)
    args = parser.parse_args(argv)

    config = load_config(args.config)
    with Path(args.decision).open() as fh:
        decision = json.load(fh)

    prices = load_store(args.store_dir)
    result = run_backtest(decision, config, prices)
    metrics = result.metrics(rf=args.rf)

    run_id = args.run_id or f"dev-{result.asof.date().isoformat()}"
    out_dir = Path(args.runs_dir) / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    equity_path = out_dir / "equity.csv"
    result.equity.to_csv(equity_path)

    metrics_path = out_dir / "metrics.json"
    payload = {
        "asof": result.asof.date().isoformat(),
        "end": result.end.date().isoformat(),
        "run_id": run_id,
        "cost_bps": result.cost_bps,
        "invested_fraction": result.invested_fraction,
        "tickers_used_equal_weight": result.tickers_used,
        "rf": args.rf,
        "metrics": metrics,
    }
    with metrics_path.open("w") as fh:
        json.dump(payload, fh, indent=2)

    print(f"Backtest: asof {payload['asof']} -> end {payload['end']}  "
          f"({len(result.equity)} trading days)")
    print(f"Equal-weight universe ({len(result.tickers_used)}): "
          f"{', '.join(result.tickers_used)}")
    print(f"Cost: {result.cost_bps} bps on {result.invested_fraction:.0%} invested\n")
    print(render_table(metrics))
    print(f"\nWrote {equity_path}\nWrote {metrics_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
