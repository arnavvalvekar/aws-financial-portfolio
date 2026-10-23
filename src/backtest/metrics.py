"""Performance metrics for an equity curve (T7, contract C5).

Pure math, no I/O. Every metric is computed from a single normalized equity
curve (a ``pandas.Series`` indexed by trading day, tz-naive, values starting
at ~1.0 at ``asof``). The same function scores the portfolio and both
baselines, so they are directly comparable.

Conventions (locked with A for v1):
  - Risk-free rate ``rf`` defaults to 0.0 (README: risk-free = zero for v1).
  - 252 trading days per year for all annualization.
  - Returns are SIMPLE daily returns of the equity curve (pct_change).
  - Sample standard deviation (ddof=1) for volatility and Sharpe.
  - max_drawdown is the most negative peak-to-trough decline, reported as a
    negative float, with the ISO dates of the prior peak and the trough.
"""
from __future__ import annotations

import math
from typing import Any

import pandas as pd

PERIODS_PER_YEAR = 252


def compute_metrics(
    equity_curve: pd.Series,
    rf: float = 0.0,
    periods_per_year: int = PERIODS_PER_YEAR,
) -> dict[str, Any]:
    """Return a metrics dict for one normalized equity curve.

    Keys:
      total_return, cagr, volatility, sharpe, max_drawdown,
      max_drawdown_peak (ISO date or None), max_drawdown_trough (ISO date or None).

    Robust to short/degenerate curves: a single point yields zeros; a flat
    curve yields zero volatility/sharpe/drawdown rather than NaN.
    """
    curve = pd.Series(equity_curve).dropna()
    if len(curve) == 0:
        return _empty_metrics()

    curve = curve.astype(float)
    start = float(curve.iloc[0])
    last = float(curve.iloc[-1])

    # --- total return -------------------------------------------------------
    total_return = (last / start) - 1.0 if start != 0 else 0.0

    # --- daily simple returns ----------------------------------------------
    returns = curve.pct_change().dropna()
    n_periods = len(returns)  # number of return steps (len(curve) - 1)

    # --- CAGR ---------------------------------------------------------------
    if n_periods >= 1 and start > 0 and last > 0:
        years = n_periods / periods_per_year
        cagr = (last / start) ** (1.0 / years) - 1.0 if years > 0 else 0.0
    else:
        cagr = 0.0

    # --- volatility (annualized sample std of daily returns) ----------------
    if n_periods >= 2:
        daily_std = float(returns.std(ddof=1))
    else:
        daily_std = 0.0
    volatility = daily_std * math.sqrt(periods_per_year)

    # --- Sharpe (annualized, rf per period = rf / periods_per_year) ---------
    if n_periods >= 2 and daily_std > 0:
        rf_daily = rf / periods_per_year
        excess_mean = float(returns.mean()) - rf_daily
        sharpe = (excess_mean / daily_std) * math.sqrt(periods_per_year)
    else:
        sharpe = 0.0

    # --- max drawdown with peak & trough dates ------------------------------
    max_dd, peak_date, trough_date = _max_drawdown(curve)

    return {
        "total_return": total_return,
        "cagr": cagr,
        "volatility": volatility,
        "sharpe": sharpe,
        "max_drawdown": max_dd,
        "max_drawdown_peak": peak_date,
        "max_drawdown_trough": trough_date,
    }


def _max_drawdown(curve: pd.Series) -> tuple[float, str | None, str | None]:
    """Most negative peak-to-trough decline and the (peak, trough) ISO dates.

    Walks the running maximum. The trough is the index of the deepest
    drawdown; the peak is the running-max index that preceded that trough.
    """
    running_max = curve.cummax()
    drawdown = curve / running_max - 1.0
    trough_pos = int(drawdown.values.argmin())
    max_dd = float(drawdown.iloc[trough_pos])

    if max_dd >= 0.0:
        # Monotonic non-decreasing curve: no drawdown.
        return 0.0, None, None

    trough_idx = curve.index[trough_pos]
    # Peak = the running-max level before/at the trough; find its first date.
    peak_level = float(running_max.iloc[trough_pos])
    peak_slice = curve.iloc[: trough_pos + 1]
    peak_matches = peak_slice[peak_slice == peak_level]
    peak_idx = peak_matches.index[0] if len(peak_matches) else curve.index[0]

    return max_dd, _iso(peak_idx), _iso(trough_idx)


def _iso(idx: Any) -> str:
    """Render an index label as an ISO ``YYYY-MM-DD`` date string."""
    ts = pd.Timestamp(idx)
    return ts.date().isoformat()


def _empty_metrics() -> dict[str, Any]:
    return {
        "total_return": 0.0,
        "cagr": 0.0,
        "volatility": 0.0,
        "sharpe": 0.0,
        "max_drawdown": 0.0,
        "max_drawdown_peak": None,
        "max_drawdown_trough": None,
    }
