"""Backtest engine tests against the committed fixture store (T7).

Uses conftest fixtures: fixture_store_dir, sample_decision, sample_config.
All offline and deterministic.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.backtest import BacktestResult, load_store, run_backtest  # noqa: E402

ASOF = pd.Timestamp("2026-01-30")
TOL = 1e-9


def test_load_store_reads_canonical(fixture_store_dir):
    store = load_store(fixture_store_dir)
    assert "SPY" in store
    assert {"AAPL", "MSFT", "KO", "NVDA"}.issubset(store.keys())
    aapl = store["AAPL"]
    assert list(aapl.columns[:2]) == ["ticker", "date"]
    assert str(aapl["date"].dtype) == "datetime64[ns]"
    # sorted ascending
    assert aapl["date"].is_monotonic_increasing


def test_three_curves_normalized_at_asof(fixture_store_dir, sample_decision, sample_config):
    store = load_store(fixture_store_dir)
    result = run_backtest(sample_decision, sample_config, store)

    assert list(result.equity.columns) == ["portfolio", "SPY", "equal_weight"]
    assert result.equity.index[0] == ASOF

    # SPY and equal_weight start at exactly 1.0 (pre-cost baselines).
    assert abs(result.equity["SPY"].iloc[0] - 1.0) < TOL
    assert abs(result.equity["equal_weight"].iloc[0] - 1.0) < TOL


def test_cost_applied_once_as_start_drag(fixture_store_dir, sample_decision, sample_config):
    store = load_store(fixture_store_dir)
    result = run_backtest(sample_decision, sample_config, store)

    # sample_decision invests 0.90 (0.10 CASH); cost = 5bps * 0.90.
    invested = 0.25 + 0.25 + 0.20 + 0.20
    assert abs(result.invested_fraction - invested) < TOL
    cost = (5 / 1e4) * invested
    # Portfolio starts at (1 - cost): all relatives are 1.0 at asof, cash=0.10.
    expected_start = (invested + 0.10) * (1.0 - cost)
    assert abs(result.equity["portfolio"].iloc[0] - expected_start) < 1e-12
    # Pre-cost the portfolio would start at exactly 1.0 (weights sum to 1).
    assert abs(expected_start / (1.0 - cost) - 1.0) < TOL


def test_cash_only_decision_is_flat_no_cost(fixture_store_dir, sample_config):
    store = load_store(fixture_store_dir)
    decision = {"asof": "2026-01-30", "weights": {"CASH": 1.0}}
    result = run_backtest(decision, sample_config, store)
    # No invested fraction -> no cost -> flat at 1.0 the whole window.
    assert result.invested_fraction == 0.0
    assert (result.equity["portfolio"] - 1.0).abs().max() < TOL


def test_equal_weight_uses_universe_tickers_in_store(fixture_store_dir, sample_config):
    store = load_store(fixture_store_dir)
    result = run_backtest({"asof": "2026-01-30", "weights": {"CASH": 1.0}}, sample_config, store)
    # Universe has 10; fixture store has AAPL, MSFT, NVDA, KO (SPY excluded).
    expected = [t for t in sample_config["universe"] if t in store]
    assert set(result.tickers_used) == set(expected)
    assert "SPY" not in result.tickers_used
    assert "CASH" not in result.tickers_used


def test_equal_weight_matches_manual_mean(fixture_store_dir, sample_config):
    store = load_store(fixture_store_dir)
    result = run_backtest({"asof": "2026-01-30", "weights": {"CASH": 1.0}}, sample_config, store)
    ew = result.tickers_used
    cal = result.equity.index

    # Rebuild equal-weight by hand from adj_close relatives.
    manual = pd.Series(0.0, index=cal)
    for t in ew:
        s = store[t].set_index("date")["adj_close"].astype(float).reindex(cal).ffill()
        manual = manual + (1.0 / len(ew)) * (s / s.iloc[0])
    pd.testing.assert_series_equal(
        result.equity["equal_weight"], manual, check_names=False, rtol=1e-12, atol=1e-12
    )


def test_missing_held_ticker_raises(fixture_store_dir, sample_config):
    store = load_store(fixture_store_dir)
    # XOM is in the universe but not in the fixture store.
    bad = {"asof": "2026-01-30", "weights": {"XOM": 1.0}}
    with pytest.raises(KeyError):
        run_backtest(bad, sample_config, store)


def test_metrics_helper_returns_all_three(fixture_store_dir, sample_decision, sample_config):
    store = load_store(fixture_store_dir)
    result = run_backtest(sample_decision, sample_config, store)
    m = result.metrics()
    assert set(m.keys()) == {"portfolio", "SPY", "equal_weight"}
    for col in m:
        assert set(m[col].keys()) >= {
            "total_return", "cagr", "volatility", "sharpe",
            "max_drawdown", "max_drawdown_peak", "max_drawdown_trough",
        }


def test_window_respects_end(fixture_store_dir, sample_decision, sample_config):
    store = load_store(fixture_store_dir)
    result = run_backtest(sample_decision, sample_config, store)
    end = pd.Timestamp(sample_config["end"])
    assert result.equity.index.max() <= end
    assert result.equity.index.min() == ASOF


def test_cli_writes_outputs_and_prints_table(fixture_store_dir, tmp_path):
    decision_path = tmp_path / "decision.json"
    decision_path.write_text(json.dumps({
        "asof": "2026-01-30",
        "weights": {"AAPL": 0.25, "MSFT": 0.25, "KO": 0.20, "NVDA": 0.20, "CASH": 0.10},
    }))
    config_path = ROOT / "tests" / "fixtures" / "config.yaml"

    proc = subprocess.run(
        [sys.executable, "-m", "src.backtest",
         "--config", str(config_path),
         "--decision", str(decision_path),
         "--store-dir", str(fixture_store_dir),
         "--runs-dir", str(tmp_path / "runs"),
         "--run-id", "test-run"],
        cwd=str(ROOT), capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert "portfolio" in proc.stdout
    assert "SPY" in proc.stdout
    assert "equal_weight" in proc.stdout
    assert "Total return" in proc.stdout

    run_dir = tmp_path / "runs" / "test-run"
    equity_csv = run_dir / "equity.csv"
    metrics_json = run_dir / "metrics.json"
    assert equity_csv.is_file()
    assert metrics_json.is_file()

    payload = json.loads(metrics_json.read_text())
    assert payload["asof"] == "2026-01-30"
    assert set(payload["metrics"].keys()) == {"portfolio", "SPY", "equal_weight"}

    df = pd.read_csv(equity_csv)
    assert {"date", "portfolio", "SPY", "equal_weight"}.issubset(df.columns)
