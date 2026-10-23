"""Backtest lane (T7): engine + metrics for post-cutoff scoring.

Public API:
  - ``run_backtest(decision, config, prices) -> BacktestResult``
  - ``compute_metrics(equity_curve, rf=0.0) -> dict``
  - ``BacktestResult`` dataclass (three equity curves + metrics() helper)
  - ``load_store(store_dir) -> {ticker: DataFrame}``
"""
from __future__ import annotations

from .engine import BacktestResult, load_store, run_backtest
from .metrics import compute_metrics

__all__ = ["run_backtest", "compute_metrics", "BacktestResult", "load_store"]
