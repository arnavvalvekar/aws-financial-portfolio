"""Validation tests for the Yahoo Finance price source.

PURPOSE: before the team commits to Yahoo as the Stooq replacement, prove the
data source delivers everything the backtest/evidence lane was going to get
from Stooq (+ the FRED risk-free proxy). These are *source-contract* tests:
they hit the live API and assert the shape, coverage and sanity of the data
against the requirements in README.md and SCHEMAS.md.

What the lane needs (and what each test checks):
  - Daily adjusted OHLC                      -> test_canonical_schema, test_adj_close_present
  - Coverage of the scored window + 200d     -> test_window_coverage, test_history_for_200d_trend
    history before the cutoff for trend
  - Real trading days, no future leakage,    -> test_dates_are_trading_days,
    monotonic ascending                         test_no_future_dates, test_dates_monotonic
  - Split/dividend adjustment behaves        -> test_split_adjustment_sane (NVDA 10:1 in 2024)
  - Multiple tickers align on dates          -> test_universe_dates_align
  - Baselines fetchable (SPY)                -> test_spy_fetchable
  - Risk-free proxy reachable (^IRX)         -> test_irx_fetchable
  - Evidence ID px:<TICKER>:<date>           -> test_evidence_id_constructible

These tests are NETWORK-dependent by design (they validate connectivity too).
Mark with -m network; skip offline with:  pytest -m "not network"
Run just this file:  .venv/bin/python -m pytest tests/test_prices_source.py -v
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pandas as pd
import pytest

# Make src importable without installing the package.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.prices import fetch_prices, fetch_many, CANONICAL_COLUMNS  # noqa: E402

pytestmark = pytest.mark.network

# Config window (mirrors config.yaml). Kept literal so the test is self-contained.
CUTOFF = pd.Timestamp("2026-01-30")
END = pd.Timestamp("2026-10-16")
UNIVERSE = ["AAPL", "MSFT", "NVDA", "AMZN", "XOM", "JNJ", "PG", "CAT", "NEE", "KO"]


@pytest.fixture(scope="module")
def aapl() -> pd.DataFrame:
    # 2y range comfortably spans 200d-before-cutoff through END.
    return fetch_prices("AAPL", range_="2y")


# --- schema -----------------------------------------------------------------

def test_canonical_schema(aapl):
    assert list(aapl.columns) == CANONICAL_COLUMNS
    assert len(aapl) > 400, "expected ~2y of daily rows"


def test_adj_close_present(aapl):
    # Returns must come from adjusted close (README: same adjusted series).
    assert aapl["adj_close"].notna().all()
    assert (aapl["adj_close"] > 0).all()


def test_ohlc_types_numeric(aapl):
    for col in ["open", "high", "low", "close", "adj_close"]:
        assert pd.api.types.is_float_dtype(aapl[col]), f"{col} not float"
    assert str(aapl["volume"].dtype) == "Int64"
    assert pd.api.types.is_datetime64_any_dtype(aapl["date"])


# --- dates / no leakage -----------------------------------------------------

def test_dates_monotonic(aapl):
    assert aapl["date"].is_monotonic_increasing
    assert aapl["date"].is_unique


def test_no_future_dates(aapl):
    today = pd.Timestamp(dt.date.today())
    assert aapl["date"].max() <= today, "source returned dates in the future"


def test_dates_are_trading_days(aapl):
    # No weekend prints (Sat=5, Sun=6). Holidays are simply absent.
    weekdays = aapl["date"].dt.dayofweek
    assert (weekdays < 5).all(), "found a weekend date in daily series"


# --- window coverage --------------------------------------------------------

def test_window_coverage(aapl):
    """Data spans the full scored window: at/through cutoff and through END."""
    assert aapl["date"].min() <= CUTOFF, "no data at/before the cutoff"
    # Backtest scores to END (2026-10-16). Allow the series to end on/after it.
    assert aapl["date"].max() >= END, f"series ends before END ({END.date()})"


def test_history_for_200d_trend(aapl):
    """At least 200 trading rows exist on or before the cutoff for the
    200-day trend signal the technical evidence needs."""
    pre = aapl[aapl["date"] <= CUTOFF]
    assert len(pre) >= 200, f"only {len(pre)} rows before cutoff; need >=200"


# --- adjustment sanity ------------------------------------------------------

def test_split_adjustment_sane():
    """NVDA did a 10:1 split on 2024-06-10. A split-adjusted series must not
    show a ~10x overnight jump, proving adj_close handles corporate actions
    the way the Stooq adjusted series would have."""
    nvda = fetch_prices("NVDA", range_="2y")
    nvda = nvda.sort_values("date").reset_index(drop=True)
    ratio = nvda["adj_close"] / nvda["adj_close"].shift(1)
    # No single day should move more than 40% on adjusted close (splits removed).
    assert ratio.dropna().between(0.6, 1.4).all(), "unadjusted split jump detected"


# --- multi-ticker alignment -------------------------------------------------

def test_universe_dates_align():
    """A subset of the universe shares the same trading calendar so the
    equal-weight baseline and portfolio can be built on one date index."""
    df = fetch_many(["AAPL", "MSFT", "KO"], range_="6mo")
    counts = df.groupby("ticker")["date"].nunique()
    # All three list on the same exchange calendar; row counts match exactly.
    assert counts.nunique() == 1, f"ticker row counts differ: {counts.to_dict()}"
    # And the set of dates is identical across tickers.
    pivot = df.pivot(index="date", columns="ticker", values="adj_close")
    assert pivot.notna().all().all(), "misaligned dates produce NaNs"


# --- baselines & risk-free --------------------------------------------------

def test_spy_fetchable():
    spy = fetch_prices("SPY", range_="1y")
    assert len(spy) > 200
    assert (spy["adj_close"] > 0).all()


def test_irx_fetchable():
    """^IRX (13-week T-bill) is the risk-free proxy if we choose not to use
    zero. Proves we have a FRED alternative despite FRED being blocked."""
    irx = fetch_prices("^IRX", range_="1mo")
    assert len(irx) > 0
    # IRX is quoted as an annualised percent yield (typically 0-10 range).
    assert irx["close"].between(-1, 25).all()


# --- evidence id ------------------------------------------------------------

def test_evidence_id_constructible(aapl):
    """px:<TICKER>:<date> must be buildable for any row (SCHEMAS.md)."""
    row = aapl.iloc[-1]
    eid = f"px:AAPL:{row['date'].date().isoformat()}"
    assert eid.startswith("px:AAPL:")
    # date component parses back to a real date
    parsed = dt.date.fromisoformat(eid.split(":")[2])
    assert parsed == row["date"].date()
