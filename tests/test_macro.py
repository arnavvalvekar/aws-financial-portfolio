"""Offline tests for the point-in-time Yahoo-proxy macro evidence pack.

Run: .venv/bin/python -m pytest tests/test_macro.py -v
"""
from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.evidence import macro  # noqa: E402


CUTOFFS = ["2025-03-31", "2026-01-30", "2026-10-16"]
PROXY_TICKERS = ("^IRX", "^TNX", "^VIX")
ID_PATTERN = re.compile(r"^px:\^(?:IRX|TNX|VIX):\d{4}-\d{2}-\d{2}$")


def test_pack_shape_and_proxy_ids():
    pack = macro.build_macro_evidence("2026-01-30")

    assert set(pack) == {"analyst", "asof", "data_horizon", "items"}
    assert pack["analyst"] == "macro"
    assert pack["asof"] == "2026-01-30"
    assert "px" in pack["data_horizon"]
    assert len(pack["items"]) == 3
    assert [item["ticker"] for item in pack["items"]] == list(PROXY_TICKERS)

    for item in pack["items"]:
        assert set(item) == {"id", "ticker", "date", "text"}
        assert item["id"] == f"px:{item['ticker']}:{item['date']}"
        assert ID_PATTERN.fullmatch(item["id"])
        assert isinstance(item["text"], str) and item["text"]


def test_items_and_horizon_never_run_past_asof():
    for asof in CUTOFFS:
        pack = macro.build_macro_evidence(asof)
        assert pack["asof"] == asof
        assert pack["data_horizon"]["px"] <= asof
        assert all(item["date"] <= asof for item in pack["items"])


def test_asof_date_and_timestamp_are_accepted():
    by_date = macro.build_macro_evidence(date(2026, 1, 30))
    by_timestamp = macro.build_macro_evidence(pd.Timestamp("2026-01-30"))

    assert by_date == by_timestamp


def test_missing_proxy_returns_disclosed_stub(tmp_path):
    # The additive macro pack must remain valid when all proxy files are absent.
    pack = macro.build_macro_evidence("2026-01-30", tmp_path)

    assert pack["analyst"] == "macro"
    assert len(pack["items"]) == 3
    assert pack["data_horizon"]["px"] == "2026-01-30"
    for item in pack["items"]:
        assert item["date"] == "2026-01-30"
        assert item["date"] <= pack["asof"]
        assert item["id"] == f"px:{item['ticker']}:2026-01-30"
        assert "insufficient" in item["text"]
        assert "disclosed" in item["text"]


def test_compute_proxy_summary_has_60_session_seam():
    dates = pd.date_range("2025-01-01", periods=61, freq="D")
    frame = pd.DataFrame({"date": dates, "value": range(61)})

    summary = macro.compute_proxy_summary(frame, "^TNX")

    assert summary["date"] == "2025-03-02"
    assert summary["value"] == 60.0
    assert summary["change_60d"] == 60.0
    assert summary["regime"] is None
