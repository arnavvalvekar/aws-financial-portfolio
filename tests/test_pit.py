"""Tests for the point-in-time guard (T3, contract C3).

Offline and deterministic: everything reads the committed T2 fixture store via
the `fixture_store_dir` conftest fixture. No network. The one test that needs an
underscore-prefixed store file (to prove it is skipped) builds a throwaway store
under pytest's `tmp_path`, so neither tests/fixtures/** nor data/** is touched.

Checklist covered (TODO.md → T3):
  1. slice inclusive over several asof values
  2. slice does not mutate its input
  3. defensive self-check RAISES on a crafted later-dated row
  4. asof accepts str / date / Timestamp (all three)
  5. slice_store(asof) == slice(load_prices(), asof)
  6. px_id format
  7. load_prices ignores "_"-prefixed files (_IRX / _manifest not loaded)
"""
from __future__ import annotations

import datetime as dt
import shutil
import sys
from pathlib import Path

import pandas as pd
import pytest

# Import shim (conftest also sets this; belt-and-suspenders if run in isolation).
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import pit  # noqa: E402
from src.data.prices import CANONICAL_COLUMNS  # noqa: E402

pytestmark = pytest.mark.filterwarnings("ignore")

FIXTURE_TICKERS = {"AAPL", "MSFT", "KO", "NVDA", "SPY"}
# asof values spanning the fixture window (2024-10-23 .. 2026-10-16).
ASOF_VALUES = ["2025-03-31", "2025-09-30", "2026-01-30", "2026-06-15"]


@pytest.fixture(scope="module")
def store_df(fixture_store_dir) -> pd.DataFrame:
    return pit.load_prices(fixture_store_dir)


# --- load_prices ------------------------------------------------------------

def test_load_prices_canonical_schema(store_df):
    assert list(store_df.columns) == CANONICAL_COLUMNS
    assert pd.api.types.is_datetime64_any_dtype(store_df["date"])
    assert store_df["date"].dt.tz is None
    assert str(store_df["volume"].dtype) == "Int64"
    for col in ("open", "high", "low", "close", "adj_close"):
        assert pd.api.types.is_float_dtype(store_df[col])
    # sorted by (ticker, date)
    assert store_df.equals(
        store_df.sort_values(["ticker", "date"]).reset_index(drop=True)
    )


# --- checklist 7: ignore "_"-prefixed files ---------------------------------

def test_load_prices_only_fixture_tickers(store_df):
    """The fixture store has no underscore files, so this pins the ticker set."""
    assert set(store_df["ticker"].unique()) == FIXTURE_TICKERS


def test_load_prices_skips_underscore_files(fixture_store_dir, tmp_path):
    """Prove "_"-prefixed files are ignored by building a throwaway store with a
    real _IRX.csv and a _manifest.json alongside two ticker CSVs."""
    store = tmp_path / "prices"
    store.mkdir()
    # Copy two real ticker CSVs.
    for t in ("AAPL", "MSFT"):
        shutil.copy(fixture_store_dir / f"{t}.csv", store / f"{t}.csv")
    # A "_"-prefixed CSV that must be skipped (clone AAPL but relabel ^IRX).
    irx = pd.read_csv(fixture_store_dir / "AAPL.csv")
    irx["ticker"] = "^IRX"
    irx.to_csv(store / "_IRX.csv", index=False)
    # A non-CSV "_"-prefixed file that must also be ignored.
    (store / "_manifest.json").write_text('{"source": "test"}')

    loaded = pit.load_prices(store)
    tickers = set(loaded["ticker"].unique())
    assert tickers == {"AAPL", "MSFT"}, tickers
    assert "^IRX" not in tickers
    assert "_IRX" not in tickers


# --- checklist 1: slice inclusive over several asof -------------------------

@pytest.mark.parametrize("asof", ASOF_VALUES)
def test_slice_inclusive(store_df, asof):
    cutoff = pd.Timestamp(asof)
    out = pit.slice(store_df, asof)
    assert len(out) > 0
    # No row past the cutoff.
    assert out["date"].max() <= cutoff
    # Inclusive: any store row exactly on the cutoff is retained.
    on_cutoff = store_df[store_df["date"] == cutoff]
    if len(on_cutoff) > 0:
        assert (out["date"] == cutoff).sum() == len(on_cutoff)
    # Slice keeps exactly the rows <= cutoff (count matches a direct filter).
    assert len(out) == int((store_df["date"] <= cutoff).sum())


def test_slice_boundary_day_retained(store_df):
    """A known trading day present in the store is kept when it equals asof."""
    # 2026-01-30 (the real cutoff) is a Friday and present in the fixtures.
    cutoff = pd.Timestamp("2026-01-30")
    assert (store_df["date"] == cutoff).any(), "expected cutoff day in fixtures"
    out = pit.slice(store_df, "2026-01-30")
    assert (out["date"] == cutoff).any()


# --- checklist 2: no mutation ----------------------------------------------

def test_slice_does_not_mutate_input(store_df):
    before_len = len(store_df)
    before_max = store_df["date"].max()
    before_hash = pd.util.hash_pandas_object(store_df, index=True).sum()

    _ = pit.slice(store_df, "2025-06-30")

    assert len(store_df) == before_len
    assert store_df["date"].max() == before_max
    after_hash = pd.util.hash_pandas_object(store_df, index=True).sum()
    assert before_hash == after_hash, "slice mutated its input frame"


# --- checklist 3: defensive self-check raises -------------------------------

def test_defensive_check_raises_on_later_row():
    """Feed a frame whose rows are all AFTER the cutoff directly to the internal
    guard — the defensive branch must raise rather than silently pass."""
    cutoff = pd.Timestamp("2026-01-30")
    crafted = pd.DataFrame(
        {
            "ticker": ["AAPL", "AAPL"],
            "date": [pd.Timestamp("2026-02-02"), pd.Timestamp("2026-03-01")],
            "open": [1.0, 1.0], "high": [1.0, 1.0], "low": [1.0, 1.0],
            "close": [1.0, 1.0], "adj_close": [1.0, 1.0],
            "volume": pd.array([1, 1], dtype="Int64"),
        }
    )
    with pytest.raises(ValueError, match="point-in-time violation"):
        pit._assert_no_future(crafted, cutoff)


def test_slice_filters_so_no_future_survives(store_df):
    """End-to-end: slice never returns a later row even when the frame contains
    many (it filters, so the defensive branch is not reached)."""
    out = pit.slice(store_df, "2025-01-15")
    assert out["date"].max() <= pd.Timestamp("2025-01-15")


# --- checklist 4: asof accepts str / date / Timestamp -----------------------

def test_asof_accepts_str_date_timestamp(store_df):
    as_str = pit.slice(store_df, "2025-09-30")
    as_date = pit.slice(store_df, dt.date(2025, 9, 30))
    as_ts = pit.slice(store_df, pd.Timestamp("2025-09-30"))
    assert len(as_str) == len(as_date) == len(as_ts)
    assert as_str.equals(as_date)
    assert as_str.equals(as_ts)


# --- checklist 5: slice_store == slice(load_prices()) -----------------------

def test_slice_store_matches_load_then_slice(fixture_store_dir):
    asof = "2026-01-30"
    combined = pit.slice_store(asof, store_dir=fixture_store_dir)
    manual = pit.slice(pit.load_prices(fixture_store_dir), asof)
    assert combined.equals(manual)


# --- checklist 6: px_id format ----------------------------------------------

def test_px_id_format():
    d = pd.Timestamp("2026-01-30")
    assert pit.px_id("AAPL", d) == "px:AAPL:2026-01-30"


def test_px_id_upcases_ticker_and_accepts_date_types():
    assert pit.px_id("aapl", "2026-01-30") == "px:AAPL:2026-01-30"
    assert pit.px_id("ko", dt.date(2025, 12, 31)) == "px:KO:2025-12-31"
    assert pit.px_id("MSFT", pd.Timestamp("2025-06-30")) == "px:MSFT:2025-06-30"
