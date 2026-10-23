"""Point-in-time macro evidence from committed Yahoo proxy series.

FRED is unavailable in the workshop network, so v1 uses the committed
price-like proxy files ``_IRX.csv``, ``_TNX.csv`` and ``_VIX.csv``.  These
series are daily observations and therefore have no release lag.  The files
are intentionally underscore-prefixed and are not loaded by ``src.pit``'s
universe price loader; this module reads them directly, filters them through
the as-of cutoff, and never performs network access.

Public API:
    build_macro_evidence(asof, store_dir="data/prices") -> dict
    compute_proxy_summary(frame, ticker) -> dict
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Union

import pandas as pd

from src import pit

AsOf = Union[str, dt.date, pd.Timestamp]

TRAILING_SESSIONS = 60
PROXIES = {
    "^IRX": {
        "file": "_IRX.csv",
        "label": "3-month Treasury rate proxy",
        "unit": "%",
    },
    "^TNX": {
        "file": "_TNX.csv",
        "label": "10-year Treasury yield proxy",
        "unit": "%",
    },
    "^VIX": {
        "file": "_VIX.csv",
        "label": "VIX volatility proxy",
        "unit": "index points",
    },
}


def _asof_timestamp(asof: AsOf) -> pd.Timestamp:
    """Normalise an accepted as-of value to a tz-naive midnight timestamp."""
    timestamp = pd.Timestamp(asof)
    if timestamp.tzinfo is not None:
        timestamp = (
            timestamp.tz_convert(None)
            if timestamp.tz is not None
            else timestamp.tz_localize(None)
        )
    return timestamp.normalize()


def _asof_iso(asof: AsOf) -> str:
    return _asof_timestamp(asof).date().isoformat()


def _read_proxy(path: Path, cutoff: pd.Timestamp) -> pd.DataFrame:
    """Read one committed proxy and retain only valid observations <= cutoff."""
    frame = pd.read_csv(path)
    if "date" not in frame.columns:
        raise ValueError(f"{path} has no date column")

    value_column = "adj_close" if "adj_close" in frame.columns else "close"
    if value_column not in frame.columns:
        raise ValueError(f"{path} has no adj_close or close column")

    out = frame[["date", value_column]].copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.tz_localize(None)
    out[value_column] = pd.to_numeric(out[value_column], errors="coerce")
    out = out.dropna(subset=["date", value_column])
    out = out[out["date"] <= cutoff].sort_values("date").reset_index(drop=True)
    return out.rename(columns={value_column: "value"})


def compute_proxy_summary(frame: pd.DataFrame, ticker: str) -> dict:
    """Compute the latest proxy value and trailing change from an as-of frame.

    ``frame`` must already contain only observations dated on or before the
    requested cutoff.  This pure function is the numeric test seam; it does not
    read files or mutate its input.  A 60-session change is used when enough
    history exists, otherwise ``change_60d`` is ``None``.
    """
    if frame.empty:
        return {
            "ticker": ticker,
            "date": None,
            "value": None,
            "change_60d": None,
            "regime": None,
        }

    values = pd.to_numeric(frame["value"], errors="coerce")
    valid = frame.loc[values.notna(), ["date"]].copy()
    valid["value"] = values.loc[valid.index].astype(float)
    valid = valid.sort_values("date").reset_index(drop=True)
    if valid.empty:
        return {
            "ticker": ticker,
            "date": None,
            "value": None,
            "change_60d": None,
            "regime": None,
        }

    latest = float(valid.iloc[-1]["value"])
    change = None
    if len(valid) > TRAILING_SESSIONS:
        prior = float(valid.iloc[-(TRAILING_SESSIONS + 1)]["value"])
        change = latest - prior

    regime = None
    if ticker == "^VIX":
        if latest < 15:
            regime = "calm"
        elif latest < 25:
            regime = "elevated"
        else:
            regime = "stressed"

    return {
        "ticker": ticker,
        "date": pd.Timestamp(valid.iloc[-1]["date"]).date().isoformat(),
        "value": latest,
        "change_60d": change,
        "regime": regime,
    }


def _format_change(change: float | None, unit: str) -> str:
    if change is None:
        return "60-session change unavailable (insufficient history)"
    if unit == "%":
        return f"60-session change {change:+.2f} percentage points"
    return f"60-session change {change:+.2f} points"


def _summary_text(ticker: str, summary: dict) -> str:
    spec = PROXIES[ticker]
    value = summary["value"]
    if spec["unit"] == "%":
        value_text = f"{value:.2f}%"
    else:
        value_text = f"{value:.2f}"
    trend = _format_change(summary["change_60d"], spec["unit"])
    regime = (
        f"; volatility regime {summary['regime']}"
        if summary["regime"] is not None
        else ""
    )
    return f"{spec['label']} {ticker} is {value_text}; {trend}{regime}."


def _disclosed_stub(ticker: str, asof_iso: str) -> dict:
    """Return a dated, valid evidence item when a proxy is unavailable."""
    return {
        "id": pit.px_id(ticker, asof_iso),
        "ticker": ticker,
        "date": asof_iso,
        "text": (
            f"insufficient data: {ticker} proxy unavailable on or before "
            f"{asof_iso}; FRED is unavailable in this environment and the "
            "macro signal is disclosed as additive, not critical-path evidence."
        ),
    }


def build_macro_evidence(
    asof: AsOf,
    store_dir: str | Path = "data/prices",
) -> dict:
    """Build a C4 macro evidence pack using committed Yahoo proxy CSVs.

    The proxy files are read locally because ``src.pit.load_prices`` correctly
    skips underscore-prefixed files.  Every row is explicitly filtered before
    summary computation, and missing or unusable proxies produce disclosed
    stub items instead of aborting the additive macro signal.
    """
    cutoff = _asof_timestamp(asof)
    asof_iso = cutoff.date().isoformat()
    store = Path(store_dir)
    items = []
    observed_dates = []

    for ticker, spec in PROXIES.items():
        path = store / spec["file"]
        try:
            frame = _read_proxy(path, cutoff)
            summary = compute_proxy_summary(frame, ticker)
        except (FileNotFoundError, OSError, KeyError, ValueError, pd.errors.EmptyDataError):
            summary = {
                "ticker": ticker,
                "date": None,
                "value": None,
                "change_60d": None,
                "regime": None,
            }

        if summary["date"] is None:
            items.append(_disclosed_stub(ticker, asof_iso))
            continue

        observed_dates.append(summary["date"])
        items.append(
            {
                "id": pit.px_id(ticker, summary["date"]),
                "ticker": ticker,
                "date": summary["date"],
                "text": _summary_text(ticker, summary),
            }
        )

    horizon = max(observed_dates) if observed_dates else asof_iso
    return {
        "analyst": "macro",
        "asof": asof_iso,
        "data_horizon": {"px": horizon},
        "items": items,
    }
