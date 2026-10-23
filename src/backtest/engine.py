"""Backtest engine (T7, contract C5).

Buy-and-hold scoring of a frozen ``decision.json`` against post-cutoff prices.

POINT-IN-TIME NOTE: this module reads later (post-cutoff) prices DIRECTLY from
the price store. That is correct — the backtest is post-cutoff scoring, the one
place allowed to see the future. Only agents/evidence go through ``pit.slice``.
This module therefore does NOT import ``src.pit``.

v1 model (locked with A):
  - rebalance = none: buy the decision weights at ``asof`` and hold to ``end``.
  - CASH earns zero return; risk-free = 0.0; 252 trading days/year.
  - 5 bps cost applied ONCE on the initial buy at ``asof`` (traded value =
    the invested, non-CASH fraction). It appears as a one-time drag so the
    portfolio curve starts at ``1 - cost`` while SPY / equal_weight start at 1.0.
  - All three equity curves are normalized to 1.0 at ``asof`` (pre-cost) so
    they are directly comparable.
  - equal_weight baseline = equal split across the config universe tickers that
    are present in the price store (not CASH).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from .metrics import compute_metrics

CASH = "CASH"
CANONICAL_COLUMNS = [
    "ticker", "date", "open", "high", "low", "close", "adj_close", "volume",
]


# --------------------------------------------------------------------------- #
# Store loading (direct reads — post-cutoff scoring, not via pit)             #
# --------------------------------------------------------------------------- #
def load_store(store_dir: str | Path) -> dict[str, pd.DataFrame]:
    """Load every ``<TICKER>.csv`` in ``store_dir`` into canonical frames.

    Returns ``{ticker: DataFrame}`` sorted by date ascending, dates parsed to
    tz-naive Timestamps. Ignores files starting with ``_`` (e.g. the manifest).
    """
    d = Path(store_dir)
    if not d.is_dir():
        raise FileNotFoundError(f"price store not found: {d}")

    store: dict[str, pd.DataFrame] = {}
    for csv in sorted(d.glob("*.csv")):
        if csv.name.startswith("_"):
            continue
        ticker = csv.stem
        df = pd.read_csv(csv)
        df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
        df = df.sort_values("date").reset_index(drop=True)
        store[ticker] = df
    if not store:
        raise FileNotFoundError(f"no price CSVs found in {d}")
    return store


# --------------------------------------------------------------------------- #
# Result container                                                            #
# --------------------------------------------------------------------------- #
@dataclass
class BacktestResult:
    """Output of :func:`run_backtest`.

    ``equity`` is a DataFrame indexed by trading day with columns
    ``portfolio``, ``SPY`` and ``equal_weight`` (each normalized to 1.0 at
    ``asof``, except the portfolio which carries the one-time cost drag).
    """

    equity: pd.DataFrame
    asof: pd.Timestamp
    end: pd.Timestamp
    tickers_used: list[str]
    cost_bps: float
    invested_fraction: float
    weights: dict[str, float] = field(default_factory=dict)
    # End-of-window price relatives for held names.  Keeping these values on
    # the result makes attribution a pure operation on the completed run: it
    # never needs to reread the post-cutoff price store.
    price_relatives: dict[str, float] = field(default_factory=dict)

    def metrics(self, rf: float = 0.0) -> dict[str, dict[str, Any]]:
        """Compute metrics for each equity column."""
        return {col: compute_metrics(self.equity[col], rf=rf) for col in self.equity.columns}

    def contributions(self) -> dict[str, float]:
        """Return additive buy-and-hold contributions to portfolio return.

        Held-name contributions are ``weight * (relative - 1)`` scaled by the
        same one-time cost drag applied to the portfolio curve.  CASH has zero
        return, while COST is the negative initial trading cost.  For valid
        decision weights (which sum to one), the rows reconcile to
        ``equity["portfolio"].iloc[-1] - 1``.
        """
        cost = (self.cost_bps / 1e4) * self.invested_fraction
        drag = 1.0 - cost

        result: dict[str, float] = {}
        for ticker, weight in self.weights.items():
            if ticker == CASH or weight == 0:
                continue
            if ticker not in self.price_relatives:
                raise KeyError(f"missing end price relative for held ticker: {ticker}")
            result[ticker] = float(weight) * (self.price_relatives[ticker] - 1.0) * drag

        # CASH earns zero return in v1.  The cost row accounts for the initial
        # buy drag, so all rows are additive to the reported portfolio return.
        result[CASH] = 0.0
        result["COST"] = -cost
        return result


# --------------------------------------------------------------------------- #
# Core                                                                        #
# --------------------------------------------------------------------------- #
def _price_series(df: pd.DataFrame) -> pd.Series:
    """adj_close indexed by date."""
    return df.set_index("date")["adj_close"].astype(float)


def _calendar(spy: pd.DataFrame, asof: pd.Timestamp, end: pd.Timestamp) -> pd.DatetimeIndex:
    """Trading-day spine from SPY within [asof, end] inclusive.

    SPY is the baseline every portfolio is compared against, so its trading
    days define the scored window. ``asof`` must exist in the SPY calendar
    (the decision cutoff is a trading day by construction).
    """
    dates = spy["date"]
    mask = (dates >= asof) & (dates <= end)
    idx = pd.DatetimeIndex(dates[mask].sort_values().unique())
    if len(idx) == 0:
        raise ValueError(f"no SPY trading days in window [{asof.date()} .. {end.date()}]")
    if idx[0] != asof:
        raise ValueError(
            f"asof {asof.date()} is not the first SPY trading day in window "
            f"(got {idx[0].date()}); asof must be a trading day on/after it"
        )
    return idx


def _relative(series: pd.Series, calendar: pd.DatetimeIndex) -> pd.Series:
    """Price relative to the asof value, reindexed onto the calendar.

    Forward-fills gaps (a ticker missing a print on a day SPY traded) so the
    curve stays defined; normalized so the value at calendar[0] == 1.0.
    """
    aligned = series.reindex(calendar).ffill()
    base = aligned.iloc[0]
    if pd.isna(base) or base == 0:
        raise ValueError("ticker has no valid price at asof")
    return aligned / base


def run_backtest(
    decision: dict,
    config: dict,
    prices: dict[str, pd.DataFrame],
) -> BacktestResult:
    """Score ``decision`` weights against ``prices`` from asof to end.

    Parameters
    ----------
    decision : dict with ``asof`` and ``weights`` (CASH optional). Only these
        two keys are read (per SCHEMAS "Backtest input").
    config : dict with ``end``, ``universe``, ``costs_bps``.
    prices : ``{ticker: canonical DataFrame}`` (e.g. from :func:`load_store`).
    """
    asof = pd.Timestamp(decision["asof"]).normalize()
    end = pd.Timestamp(config["end"]).normalize()
    weights: dict[str, float] = dict(decision["weights"])
    universe: list[str] = list(config["universe"])
    cost_bps = float(config.get("costs_bps", 0.0))

    if "SPY" not in prices:
        raise KeyError("price store must contain SPY (the baseline calendar)")
    calendar = _calendar(prices["SPY"], asof, end)

    # --- portfolio curve: sum of weight_i * price_relative_i ---------------- #
    held = {t: w for t, w in weights.items() if t != CASH and w != 0}
    missing = [t for t in held if t not in prices]
    if missing:
        raise KeyError(f"decision holds tickers with no price data: {missing}")

    portfolio = pd.Series(0.0, index=calendar)
    price_relatives: dict[str, float] = {}
    for ticker, w in held.items():
        relative = _relative(_price_series(prices[ticker]), calendar)
        price_relatives[ticker] = float(relative.iloc[-1])
        portfolio = portfolio + w * relative
    cash_w = float(weights.get(CASH, 0.0))
    portfolio = portfolio + cash_w * 1.0  # CASH holds its value (zero return)

    # One-time cost on the initial buy: traded value = invested (non-CASH)
    # fraction. Applied as a drag so the curve starts at (1 - cost).
    invested_fraction = float(sum(held.values()))
    cost = (cost_bps / 1e4) * invested_fraction
    portfolio = portfolio * (1.0 - cost)

    # --- SPY baseline (normalized to 1.0, no cost) -------------------------- #
    spy_curve = _relative(_price_series(prices["SPY"]), calendar)

    # --- equal-weight baseline: 1/N across universe tickers in the store ---- #
    ew_tickers = [t for t in universe if t in prices]
    if not ew_tickers:
        raise KeyError("no universe tickers present in price store for equal_weight")
    n = len(ew_tickers)
    equal_weight = pd.Series(0.0, index=calendar)
    for ticker in ew_tickers:
        equal_weight = equal_weight + (1.0 / n) * _relative(_price_series(prices[ticker]), calendar)

    equity = pd.DataFrame(
        {
            "portfolio": portfolio,
            "SPY": spy_curve,
            "equal_weight": equal_weight,
        }
    )
    equity.index.name = "date"

    return BacktestResult(
        equity=equity,
        asof=asof,
        end=end,
        tickers_used=ew_tickers,
        cost_bps=cost_bps,
        invested_fraction=invested_fraction,
        weights=weights,
        price_relatives=price_relatives,
    )
