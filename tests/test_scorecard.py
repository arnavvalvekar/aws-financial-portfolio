"""Tests for the analyst scorecard (Phase 3 stretch).

Offline on the T2 fixture store (AAPL/MSFT/KO/NVDA/SPY). The pure scoring seam
``score_analyst`` is hand-checked; ``build_scorecard`` is exercised end-to-end
against a synthesized analyst pack written into a tmp run dir.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.backtest import scorecard  # noqa: E402

ASOF = "2026-01-30"
END = "2026-10-16"
UNIVERSE = ["AAPL", "MSFT", "KO", "NVDA"]


# --- pure scoring seam ------------------------------------------------------

def test_score_analyst_hit_rate_and_sign():
    # Two correct directional calls, one wrong. Returns: AAPL up, MSFT down, KO up.
    returns = {"AAPL": 0.20, "MSFT": -0.10, "KO": 0.05}
    views = [
        {"ticker": "AAPL", "stance": 0.8},   # bullish, up  -> hit
        {"ticker": "MSFT", "stance": -0.6},  # bearish, down-> hit
        {"ticker": "KO", "stance": -0.4},    # bearish, up  -> miss
    ]
    s = scorecard.score_analyst(views, returns)
    assert s["n_views"] == 3
    assert s["hit_rate"] == pytest.approx(2 / 3)
    # stance-weighted: (.8*.2 + -.6*-.1 + -.4*.05)/3 = (.16+.06-.02)/3
    assert s["stance_weighted_ret"] == pytest.approx((0.16 + 0.06 - 0.02) / 3)


def test_score_analyst_ignores_unknown_and_null():
    returns = {"AAPL": 0.1}
    views = [
        {"ticker": "AAPL", "stance": 0.5},
        {"ticker": "ZZZZ", "stance": 0.9},   # not in returns -> ignored
        {"ticker": "MSFT", "stance": None},  # null stance -> ignored
    ]
    s = scorecard.score_analyst(views, returns)
    assert s["n_views"] == 1


def test_score_analyst_flat_stance_not_counted_in_hit_rate():
    returns = {"AAPL": 0.1, "KO": -0.1}
    views = [
        {"ticker": "AAPL", "stance": 0.01},  # below EPS -> not a directional call
        {"ticker": "KO", "stance": -0.5},    # bearish, down -> hit
    ]
    s = scorecard.score_analyst(views, returns)
    assert s["n_views"] == 2
    assert s["hit_rate"] == pytest.approx(1.0)  # only KO counted, and it hit


def test_spearman_perfect_and_inverse():
    assert scorecard._spearman([1, 2, 3], [10, 20, 30]) == pytest.approx(1.0)
    assert scorecard._spearman([1, 2, 3], [30, 20, 10]) == pytest.approx(-1.0)
    assert scorecard._spearman([1], [1]) is None  # too few points


# --- forward returns on the fixture store -----------------------------------

def test_forward_returns_on_fixtures(fixture_store_dir):
    r = scorecard.forward_returns(UNIVERSE, ASOF, END, store_dir=str(fixture_store_dir))
    assert set(r) == set(UNIVERSE)
    for v in r.values():
        assert isinstance(v, float)


# --- end to end -------------------------------------------------------------

def test_build_scorecard_end_to_end(fixture_store_dir, tmp_path, sample_config):
    run = tmp_path / "run"
    (run / "analysts").mkdir(parents=True)
    (run / "metrics.json").write_text(json.dumps({"asof": ASOF, "end": END}))
    (run / "analysts" / "technical.json").write_text(json.dumps({
        "analyst": "technical", "asof": ASOF,
        "views": [{"ticker": t, "stance": 0.3} for t in UNIVERSE],
    }))
    config = {"universe": UNIVERSE, "asof": ASOF, "end": END}
    sc = scorecard.build_scorecard(run, config, store_dir=str(fixture_store_dir))
    assert "technical" in sc["analysts"]
    assert sc["analysts"]["technical"]["n_views"] == len(UNIVERSE)
    assert isinstance(sc["ranking"], list)
    # render smoke
    text = scorecard.render_scorecard(sc)
    assert "technical" in text


def test_build_scorecard_no_packs_is_flagged(fixture_store_dir, tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    (run / "metrics.json").write_text(json.dumps({"asof": ASOF, "end": END}))
    config = {"universe": UNIVERSE, "asof": ASOF, "end": END}
    sc = scorecard.build_scorecard(run, config, store_dir=str(fixture_store_dir))
    assert sc["analysts"] == {}
    assert "note" in sc
