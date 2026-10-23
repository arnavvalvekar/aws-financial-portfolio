"""No-look-ahead leakage test (T4, the guard that is NEVER cut).

The cutoff is a one-way valve: nothing dated after `asof` may reach an analyst.
This test is the skeptical judge — it proves, offline and deterministically,
that the only door to data (`pit.slice` / `pit.slice_store`) never leaks a
future row, across every fixture ticker, at several cutoffs.

Two layers:
  1. SLICE level — property-test over several asof dates (an early date,
     2025-06-30, 2025-09-30, and the real cutoff 2026-01-30). No returned row,
     for ANY ticker, may be dated after asof.
  2. EVIDENCE-PACK level — if `src/evidence/technical.py` exists, the technical
     evidence pack built at asof must contain no item dated after asof. The
     module is not built yet, so this layer `importorskip`s and skips cleanly.
     *** T8 MUST re-run this file once T6 (technical evidence) lands so the
     evidence-pack layer actually executes. ***

Offline only: reads the committed T2 fixture store via `fixture_store_dir`.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

# Import shim (conftest sets this too; kept for isolated runs).
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import pit  # noqa: E402

# >=3 asof dates, including the real cutoff 2026-01-30, spanning the fixture
# window (2024-10-23 .. 2026-10-16).
ASOF_DATES = ["2025-01-15", "2025-06-30", "2025-09-30", "2026-01-30"]

# Fixture equities only (SPY is a baseline, not an analyst name).
FIXTURE_EQUITIES = ["AAPL", "MSFT", "KO", "NVDA"]


@pytest.fixture(scope="module")
def store_df(fixture_store_dir) -> pd.DataFrame:
    return pit.load_prices(fixture_store_dir)


# --- layer 1: slice-level leakage ------------------------------------------

@pytest.mark.parametrize("asof", ASOF_DATES)
def test_slice_has_no_future_row(store_df, asof):
    """Across ALL fixture tickers, pit.slice returns no row dated after asof."""
    cutoff = pd.Timestamp(asof)
    out = pit.slice(store_df, asof)

    # Non-vacuous: there must be data at/before each chosen cutoff.
    assert len(out) > 0, f"no rows at/before {asof}; test would be vacuous"

    # Global guarantee.
    assert out["date"].max() <= cutoff, (
        f"leak: a row dated after {asof} survived the slice"
    )

    # Per-ticker guarantee — a leak in any single ticker is caught, not just
    # hidden by the aggregate max.
    per_ticker_max = out.groupby("ticker")["date"].max()
    leaking = per_ticker_max[per_ticker_max > cutoff]
    assert leaking.empty, f"leak per ticker after {asof}: {leaking.to_dict()}"


@pytest.mark.parametrize("asof", ASOF_DATES)
def test_slice_store_has_no_future_row(fixture_store_dir, asof):
    """Same guarantee through the load+slice convenience path (slice_store)."""
    cutoff = pd.Timestamp(asof)
    out = pit.slice_store(asof, store_dir=fixture_store_dir)
    assert len(out) > 0
    assert out["date"].max() <= cutoff
    for ticker, grp in out.groupby("ticker"):
        assert grp["date"].max() <= cutoff, f"{ticker} leaks after {asof}"


def test_every_fixture_ticker_present_before_cutoff(store_df):
    """Guards the property test itself: every equity we claim to check actually
    has pre-cutoff data in the fixtures (so the asserts above are meaningful)."""
    out = pit.slice(store_df, "2026-01-30")
    present = set(out["ticker"].unique())
    for t in FIXTURE_EQUITIES:
        assert t in present, f"{t} missing from fixture store before cutoff"


# --- layer 2: evidence-pack-level leakage (conditional) ---------------------

@pytest.mark.parametrize("asof", ASOF_DATES)
def test_technical_evidence_pack_has_no_future_item(fixture_store_dir, asof):
    """If the technical evidence module exists, the pack built at asof must have
    no item dated after asof. Skips until T6 lands (then T8 re-runs this)."""
    technical = pytest.importorskip(
        "src.evidence.technical",
        reason="src/evidence/technical.py not built yet (T6); T8 must re-run.",
    )
    cutoff = pd.Timestamp(asof)
    pack = technical.build_technical_evidence(
        asof, FIXTURE_EQUITIES, store_dir=str(fixture_store_dir)
    )
    assert pack.get("asof") == asof or pd.Timestamp(pack["asof"]) == cutoff
    items = pack.get("items", [])
    assert len(items) > 0, "evidence pack produced no items"
    for item in items:
        item_date = pd.Timestamp(item["date"])
        assert item_date <= cutoff, (
            f"leak: evidence item {item.get('id')} dated {item['date']} > {asof}"
        )


# --- layer 3: Phase 2 evidence packs (P2-4) --------------------------------
# The macro and crash-risk/regime packs must obey the same no-look-ahead rule
# as the technical pack: nothing dated after asof may appear. These activate
# now that src/evidence/macro.py and src/evidence/regime.py exist.

@pytest.mark.parametrize("asof", ASOF_DATES)
def test_macro_evidence_pack_has_no_future_item(fixture_store_dir, asof):
    macro = pytest.importorskip(
        "src.evidence.macro",
        reason="src/evidence/macro.py not built yet (P2-1).",
    )
    cutoff = pd.Timestamp(asof)
    pack = macro.build_macro_evidence(asof, store_dir=str(fixture_store_dir))
    assert pd.Timestamp(pack["asof"]) == cutoff
    for item in pack.get("items", []):
        # Stub/disclosure items may omit a concrete date; only check dated ones.
        if item.get("date"):
            item_date = pd.Timestamp(item["date"])
            assert item_date <= cutoff, (
                f"leak: macro item {item.get('id')} dated {item['date']} > {asof}"
            )


@pytest.mark.parametrize("asof", ASOF_DATES)
def test_regime_evidence_pack_has_no_future_item(fixture_store_dir, asof):
    regime = pytest.importorskip(
        "src.evidence.regime",
        reason="src/evidence/regime.py not built yet (P2-3).",
    )
    cutoff = pd.Timestamp(asof)
    pack = regime.build_regime_evidence(
        asof, FIXTURE_EQUITIES, store_dir=str(fixture_store_dir)
    )
    items = pack.get("items", [])
    assert len(items) > 0, "regime pack produced no items"
    for item in items:
        if item.get("date"):
            item_date = pd.Timestamp(item["date"])
            assert item_date <= cutoff, (
                f"leak: regime item {item.get('id')} dated {item['date']} > {asof}"
            )
