"""Hand-checked unit tests for compute_metrics (T7).

Every expected value below is computed by hand from the tiny series so the
metric math is pinned, not just internally consistent.
"""
from __future__ import annotations

import math
from pathlib import Path
import sys

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.backtest.metrics import compute_metrics  # noqa: E402

TOL = 1e-9


def _series(values, start="2026-01-30"):
    idx = pd.bdate_range(start=start, periods=len(values))
    return pd.Series(values, index=idx)


def test_total_return_and_drawdown_dates():
    # Curve: 1.0 -> 1.1 -> 1.05 -> 1.2 over 4 business days.
    dates = pd.to_datetime(["2026-01-30", "2026-02-02", "2026-02-03", "2026-02-04"])
    curve = pd.Series([1.0, 1.1, 1.05, 1.2], index=dates)
    m = compute_metrics(curve)

    # total_return = 1.2/1.0 - 1 = 0.2
    assert abs(m["total_return"] - 0.2) < TOL

    # daily simple returns: 0.1, -0.0454545..., 0.142857...
    r1 = 1.1 / 1.0 - 1
    r2 = 1.05 / 1.1 - 1
    r3 = 1.2 / 1.05 - 1
    returns = [r1, r2, r3]
    mean = sum(returns) / 3
    var = sum((x - mean) ** 2 for x in returns) / (3 - 1)  # ddof=1
    std = math.sqrt(var)

    assert abs(m["volatility"] - std * math.sqrt(252)) < 1e-12
    assert abs(m["sharpe"] - (mean / std) * math.sqrt(252)) < 1e-12

    # CAGR: (1.2)^(252/3) - 1
    expected_cagr = (1.2) ** (252 / 3) - 1
    assert abs(m["cagr"] - expected_cagr) / expected_cagr < 1e-9

    # max drawdown: worst is 1.05/1.1 - 1 = -0.0454545...
    expected_dd = 1.05 / 1.1 - 1
    assert abs(m["max_drawdown"] - expected_dd) < TOL
    # peak was 1.1 on 2026-02-02, trough 1.05 on 2026-02-03
    assert m["max_drawdown_peak"] == "2026-02-02"
    assert m["max_drawdown_trough"] == "2026-02-03"


def test_flat_curve_is_all_zero():
    curve = _series([1.0, 1.0, 1.0, 1.0])
    m = compute_metrics(curve)
    assert m["total_return"] == 0.0
    assert m["cagr"] == 0.0
    assert m["volatility"] == 0.0
    assert m["sharpe"] == 0.0
    assert m["max_drawdown"] == 0.0
    assert m["max_drawdown_peak"] is None
    assert m["max_drawdown_trough"] is None


def test_monotonic_up_has_no_drawdown():
    curve = _series([1.0, 1.1, 1.2, 1.3])
    m = compute_metrics(curve)
    assert m["max_drawdown"] == 0.0
    assert m["max_drawdown_peak"] is None
    assert m["max_drawdown_trough"] is None
    assert m["total_return"] > 0


def test_single_point_is_degenerate_zero():
    curve = _series([1.0])
    m = compute_metrics(curve)
    assert m["total_return"] == 0.0
    assert m["volatility"] == 0.0
    assert m["sharpe"] == 0.0
    assert m["max_drawdown"] == 0.0


def test_pure_decline_drawdown():
    # 1.0 -> 0.9 -> 0.8: peak at start, trough at end.
    dates = pd.to_datetime(["2026-01-30", "2026-02-02", "2026-02-03"])
    curve = pd.Series([1.0, 0.9, 0.8], index=dates)
    m = compute_metrics(curve)
    assert abs(m["max_drawdown"] - (0.8 / 1.0 - 1)) < TOL
    assert m["max_drawdown_peak"] == "2026-01-30"
    assert m["max_drawdown_trough"] == "2026-02-03"
    assert abs(m["total_return"] - (-0.2)) < TOL


def test_rf_lowers_sharpe():
    curve = _series([1.0, 1.02, 1.01, 1.05, 1.08])
    base = compute_metrics(curve, rf=0.0)
    withrf = compute_metrics(curve, rf=0.05)
    # Positive rf reduces excess return -> lower Sharpe.
    assert withrf["sharpe"] < base["sharpe"]
    # Volatility is independent of rf.
    assert abs(withrf["volatility"] - base["volatility"]) < TOL
