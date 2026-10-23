"""T6 tests — technical evidence pack, offline on the T2 fixture store.

All data access in the module under test goes through ``src.pit``; these tests
read fixtures the same way (via pit) so they never hit the network. Numeric
hand-checks recompute momentum and the SMA cross independently from the sliced
adj_close series and assert the module agrees.

Run: .venv/bin/python -m pytest tests/test_technical.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# import shim (mirrors conftest / test_prices_source) so `src` imports work.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import pit  # noqa: E402
from src.evidence import technical  # noqa: E402

CUTOFF = "2026-01-30"
EARLY = "2025-03-01"            # 87 AAPL fixture rows: >=64 (momentum ok), <200 (sma200 null)
UNIVERSE = ["AAPL", "MSFT", "KO", "NVDA"]   # fixture equities (SPY is a baseline, not universe)


def _sliced(fixture_store_dir, ticker, asof):
    df = pit.slice_store(asof, str(fixture_store_dir))
    return df[df["ticker"] == ticker].sort_values("date").reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Pack shape / C4 conformance
# --------------------------------------------------------------------------- #
def test_pack_shape_is_c4(fixture_store_dir):
    pack = technical.build_technical_evidence(CUTOFF, UNIVERSE, str(fixture_store_dir))

    assert pack["analyst"] == "technical"
    assert pack["asof"] == CUTOFF
    assert set(pack["data_horizon"].keys()) == {"px"}
    # data_horizon.px is a real trading day on or before the cutoff.
    assert pack["data_horizon"]["px"] <= CUTOFF

    # One item per universe ticker, in order.
    assert [it["ticker"] for it in pack["items"]] == UNIVERSE

    for it in pack["items"]:
        # STRICT four-field C4 item — no extra keys (Option A).
        assert set(it.keys()) == {"id", "ticker", "date", "text"}
        assert it["id"] == pit.px_id(it["ticker"], CUTOFF)
        assert it["id"] == f"px:{it['ticker']}:{CUTOFF}"
        assert it["date"] == CUTOFF
        assert isinstance(it["text"], str) and it["text"]


def test_no_date_after_asof(fixture_store_dir):
    pack = technical.build_technical_evidence(CUTOFF, UNIVERSE, str(fixture_store_dir))
    for it in pack["items"]:
        assert it["date"] <= CUTOFF
    assert pack["data_horizon"]["px"] <= CUTOFF


def test_full_history_text_not_insufficient(fixture_store_dir):
    # At the cutoff every fixture ticker has 318 rows -> real summary, not the marker.
    pack = technical.build_technical_evidence(CUTOFF, UNIVERSE, str(fixture_store_dir))
    for it in pack["items"]:
        assert it["text"] != technical.INSUFFICIENT_TEXT


# --------------------------------------------------------------------------- #
# Numeric hand-checks via the compute_signals seam
# --------------------------------------------------------------------------- #
def test_momentum_hand_check(fixture_store_dir):
    tdf = _sliced(fixture_store_dir, "AAPL", CUTOFF)
    sig = technical.compute_signals(tdf)

    adj = tdf["adj_close"].to_numpy(dtype=float)
    # momentum_63d = adj[-1]/adj[-64] - 1 ; momentum_126d = adj[-1]/adj[-127] - 1
    expected_63 = adj[-1] / adj[-(63 + 1)] - 1.0
    expected_126 = adj[-1] / adj[-(126 + 1)] - 1.0

    assert sig["momentum_63d"] == pytest.approx(expected_63, rel=1e-12, abs=1e-12)
    assert sig["momentum_126d"] == pytest.approx(expected_126, rel=1e-12, abs=1e-12)


def test_sma_cross_hand_check(fixture_store_dir):
    tdf = _sliced(fixture_store_dir, "AAPL", CUTOFF)
    sig = technical.compute_signals(tdf)

    adj = tdf["adj_close"].to_numpy(dtype=float)
    expected_sma50 = float(np.mean(adj[-50:]))
    expected_sma200 = float(np.mean(adj[-200:]))
    if expected_sma50 > expected_sma200:
        expected_cross = "golden"
    elif expected_sma50 < expected_sma200:
        expected_cross = "death"
    else:
        expected_cross = "flat"

    assert sig["sma50"] == pytest.approx(expected_sma50, rel=1e-12)
    assert sig["sma200"] == pytest.approx(expected_sma200, rel=1e-12)
    assert sig["sma_cross"] == expected_cross
    assert sig["close_vs_sma50"] == bool(adj[-1] >= expected_sma50)
    assert sig["close_vs_sma200"] == bool(adj[-1] >= expected_sma200)


def test_vol_hand_check(fixture_store_dir):
    tdf = _sliced(fixture_store_dir, "AAPL", CUTOFF)
    sig = technical.compute_signals(tdf)

    adj = tdf["adj_close"].to_numpy(dtype=float)
    tail = adj[-(20 + 1):]
    daily = tail[1:] / tail[:-1] - 1.0
    expected = float(np.std(daily, ddof=1) * np.sqrt(252))
    assert sig["vol_20d_annualized"] == pytest.approx(expected, rel=1e-12)


# --------------------------------------------------------------------------- #
# Insufficient-history path (<200 rows): Option A — null only unmet signals
# --------------------------------------------------------------------------- #
def test_insufficient_history_signals(fixture_store_dir):
    tdf = _sliced(fixture_store_dir, "AAPL", EARLY)
    assert len(tdf) < technical.MIN_HISTORY      # precondition: < 200 rows
    assert len(tdf) >= 64                         # precondition: momentum_63d computable

    sig = technical.compute_signals(tdf)
    # 200-day signals null...
    assert sig["sma200"] is None
    assert sig["close_vs_sma200"] is None
    assert sig["sma_cross"] is None
    # ...but short-window signals that ARE computable stay populated (Option A).
    assert sig["momentum_63d"] is not None
    assert sig["sma50"] is not None              # 87 rows >= 50


def test_insufficient_history_text(fixture_store_dir):
    pack = technical.build_technical_evidence(EARLY, ["AAPL"], str(fixture_store_dir))
    item = pack["items"][0]
    assert item["ticker"] == "AAPL"
    assert item["text"] == technical.INSUFFICIENT_TEXT
    assert item["id"] == pit.px_id("AAPL", EARLY)


def test_unknown_ticker_is_insufficient(fixture_store_dir):
    # A ticker not in the store yields zero rows -> insufficient history, no crash.
    pack = technical.build_technical_evidence(CUTOFF, ["ZZZZ"], str(fixture_store_dir))
    item = pack["items"][0]
    assert item["text"] == technical.INSUFFICIENT_TEXT
    assert item["id"] == pit.px_id("ZZZZ", CUTOFF)
