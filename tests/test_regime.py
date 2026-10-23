"""Offline tests for point-in-time regime-fragility evidence."""
from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import pit  # noqa: E402
from src.evidence import regime  # noqa: E402

UNIVERSE = ["AAPL", "MSFT", "KO", "NVDA"]
CUTOFF = "2026-01-30"


def _summary(pack):
    return next(item for item in pack["items"] if item["id"].startswith("regime:"))


def _score_from_text(text):
    match = re.search(r"crash_risk_score=([0-9.]+)", text)
    assert match
    return float(match.group(1))


def test_pack_shape_and_score_band(fixture_store_dir):
    pack = regime.build_regime_evidence(CUTOFF, UNIVERSE, str(fixture_store_dir))

    assert set(pack) == {"analyst", "asof", "data_horizon", "items"}
    assert pack["analyst"] == "regime"
    assert pack["asof"] == CUTOFF
    assert set(pack["data_horizon"]) == {"px"}
    assert pack["data_horizon"]["px"] <= CUTOFF
    assert len(pack["items"]) == len(UNIVERSE) + 1

    summary = _summary(pack)
    score = _score_from_text(summary["text"])
    band = re.search(r"band=(calm|elevated|stressed)", summary["text"]).group(1)
    assert 0.0 <= score <= 1.0
    expected = "calm" if score < 0.33 else "elevated" if score <= 0.66 else "stressed"
    assert band == expected

    assert summary["id"] == f"regime:{CUTOFF}"
    assert summary["ticker"] == "SPY"
    for item in pack["items"]:
        assert set(item) == {"id", "ticker", "date", "text"}
        assert item["date"] <= CUTOFF
    for ticker, item in zip(UNIVERSE, pack["items"][1:]):
        assert item["ticker"] == ticker
        assert item["id"] == pit.px_id(ticker, CUTOFF)


def test_compute_regime_components_are_hand_checkable(fixture_store_dir):
    sliced = pit.slice_store(CUTOFF, str(fixture_store_dir))
    result = regime.compute_regime(sliced, UNIVERSE)

    spy = sliced[sliced["ticker"] == "SPY"].sort_values("date")
    adj = spy["adj_close"].to_numpy(dtype=float)
    peak = np.max(adj[-252:])
    expected_drawdown = float(adj[-1] / peak - 1.0)
    assert result["market_drawdown"] == pytest.approx(expected_drawdown)
    assert result["market_drawdown_component"] == pytest.approx(max(-expected_drawdown, 0.0))
    assert 0.0 <= result["crash_risk_score"] <= 1.0
    assert set(result["components"]) == {
        "market_drawdown",
        "volatility_spike",
        "below_sma200",
    }


def test_drawdown_and_breadth_regime_is_higher_than_calm(fixture_store_dir):
    # Start with the frozen fixture at the cutoff, then deliberately craft a
    # point-in-time stress snapshot: SPY is below its trailing peak and three
    # of four universe names are below their 200-day SMA.  No future row is
    # introduced; this is a pure numeric seam hand-check.
    calm_frame = pit.slice_store(CUTOFF, str(fixture_store_dir))
    crafted_frame = calm_frame.copy()
    spy_rows = crafted_frame[crafted_frame["ticker"] == "SPY"]
    spy_peak = spy_rows["adj_close"].tail(252).max()
    spy_last = spy_rows.index[-1]
    crafted_frame.loc[spy_last, "adj_close"] = float(spy_peak * 0.50)
    for ticker in UNIVERSE[:3]:
        rows = crafted_frame[crafted_frame["ticker"] == ticker]
        last = rows.index[-1]
        sma200 = rows["adj_close"].tail(200).mean()
        crafted_frame.loc[last, "adj_close"] = float(sma200 * 0.50)

    stressed = regime.compute_regime(crafted_frame, UNIVERSE)
    calm = regime.compute_regime(calm_frame, UNIVERSE)

    assert stressed["market_drawdown"] < 0
    assert stressed["below_sma200_fraction"] > 0.5
    assert stressed["crash_risk_score"] > calm["crash_risk_score"]


@pytest.mark.parametrize("asof", ["2024-12-31", "2025-06-30", "2025-10-10", CUTOFF])
def test_no_item_date_after_asof(fixture_store_dir, asof):
    pack = regime.build_regime_evidence(asof, UNIVERSE, str(fixture_store_dir))
    assert pack["asof"] == asof
    assert pack["data_horizon"]["px"] <= asof
    assert all(item["date"] <= asof for item in pack["items"])


def test_optional_vix_is_cut_off_before_use(tmp_path, fixture_store_dir):
    # Copy only the fixture ticker files and add a headerless VIX series whose
    # future row must not affect the as-of calculation.
    store = tmp_path / "prices"
    store.mkdir()
    for path in Path(fixture_store_dir).glob("*.csv"):
        (store / path.name).write_bytes(path.read_bytes())
    vix = pd.DataFrame(
        [
            ["^VIX", "2026-01-29", 18, 18, 18, 18, 18, 0],
            ["^VIX", "2026-01-30", 20, 20, 20, 20, 20, 0],
            ["^VIX", "2026-02-02", 99, 99, 99, 99, 99, 0],
        ]
    )
    vix.to_csv(store / "_VIX.csv", index=False, header=False)

    pack = regime.build_regime_evidence(CUTOFF, UNIVERSE, str(store))
    summary = _summary(pack)
    assert "vix=20.0000" in summary["text"]
    assert "99.0000" not in summary["text"]
    assert summary["date"] <= CUTOFF
