"""Offline tests for buy-and-hold contribution attribution."""
from __future__ import annotations

import pandas as pd

from src.backtest import load_store, run_backtest
from src.backtest.attribution import sorted_contributions


TOL = 1e-6


def test_contributions_reconcile_to_portfolio_return(
    fixture_store_dir, sample_decision, sample_config
):
    result = run_backtest(
        sample_decision, sample_config, load_store(fixture_store_dir)
    )

    contributions = result.contributions()
    portfolio_return = float(result.equity["portfolio"].iloc[-1] - 1.0)

    assert set(contributions) == {"AAPL", "MSFT", "KO", "NVDA", "CASH", "COST"}
    assert abs(sum(contributions.values()) - portfolio_return) <= TOL


def test_name_contribution_uses_end_relative_and_cost_drag(
    fixture_store_dir, sample_decision, sample_config
):
    store = load_store(fixture_store_dir)
    result = run_backtest(sample_decision, sample_config, store)

    ticker = "AAPL"
    prices = (
        store[ticker]
        .set_index("date")["adj_close"]
        .astype(float)
        .reindex(result.equity.index)
        .ffill()
    )
    relative_end = float(prices.iloc[-1] / prices.iloc[0])
    cost = (result.cost_bps / 1e4) * result.invested_fraction
    expected = sample_decision["weights"][ticker] * (relative_end - 1.0) * (1.0 - cost)

    assert abs(result.contributions()[ticker] - expected) <= TOL


def test_cash_is_zero_and_breakdown_is_sorted(
    fixture_store_dir, sample_decision, sample_config
):
    result = run_backtest(
        sample_decision, sample_config, load_store(fixture_store_dir)
    )
    contributions = result.contributions()

    assert contributions["CASH"] == 0.0
    assert contributions["COST"] < 0.0

    breakdown = sorted_contributions(contributions)
    assert [abs(value) for _, value in breakdown] == sorted(
        (abs(value) for value in contributions.values()), reverse=True
    )
    assert breakdown[0][0] == max(contributions, key=lambda name: abs(contributions[name]))
