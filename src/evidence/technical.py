"""T6 — Technical evidence pack (contract C4 / SCHEMAS.md).

Builds the ``technical`` analyst's evidence pack at a given ``asof``. Every row
of price data is read through ``src.pit`` (``slice_store``), so the
point-in-time guard is the single gate — this module never reads CSVs or the
network directly, and nothing in the pack can be dated after ``asof``.

Signals per ticker (all computed from ``adj_close``, on rows dated <= asof):
  - momentum_63d, momentum_126d : total return over the trailing N trading days
  - vol_20d_annualized          : std of last 20 daily returns, x sqrt(252)
  - drawdown_252d               : min peak-to-trough over the trailing 252 rows
  - trend                       : last close vs SMA50 / SMA200, and the
                                  SMA50-vs-SMA200 cross (golden / death / flat)

Insufficient-history policy (locked with A):
  - Null ONLY the signals whose own lookback is not met (e.g. a young ticker
    still reports momentum_63d if it has >= 64 rows, even when SMA200 is null).
  - When the 200-day trend cannot be computed (< 200 rows at asof), the item
    ``text`` is exactly "insufficient history". Signals are never fabricated.

Contract C4 item shape is STRICT four-field (locked with A): each item is
``{id, ticker, date, text}`` only — the numeric signals are summarised in
``text`` (B's analyst reads the sentence). ``compute_signals`` is exposed as an
internal public helper so the numbers can be unit-tested directly without
widening the pack schema.

Public API (C4):
    build_technical_evidence(asof, universe, store_dir="data/prices") -> dict
    compute_signals(frame) -> dict   # internal seam, pure fn on a sliced frame
"""
from __future__ import annotations

import datetime as dt
from typing import Iterable, Union

import numpy as np
import pandas as pd

from src import pit

AsOf = Union[str, dt.date, pd.Timestamp]

# Lookback windows (trading days).
MOM_SHORT = 63
MOM_LONG = 126
VOL_WINDOW = 20
DD_WINDOW = 252
SMA_FAST = 50
SMA_SLOW = 200
TRADING_DAYS = 252

# Below this many rows at asof the flagship 200-day trend is unavailable and the
# item text is marked "insufficient history".
MIN_HISTORY = SMA_SLOW  # 200
INSUFFICIENT_TEXT = "insufficient history"


def _asof_iso(asof: AsOf) -> str:
    """ISO ``YYYY-MM-DD`` for ``asof``, tz-naive (mirrors pit normalisation)."""
    ts = pd.Timestamp(asof)
    if ts.tzinfo is not None:
        ts = ts.tz_convert(None) if ts.tz is not None else ts.tz_localize(None)
    return ts.date().isoformat()


def _total_return(adj: np.ndarray, window: int):
    """Total return over the trailing ``window`` days, or None if too short.

    Needs ``window + 1`` observations (price now and price ``window`` days ago).
    """
    if len(adj) < window + 1:
        return None
    past = adj[-(window + 1)]
    if past == 0 or np.isnan(past):
        return None
    return float(adj[-1] / past - 1.0)


def _realized_vol(adj: np.ndarray, window: int):
    """Annualised stdev of the last ``window`` daily simple returns, or None."""
    if len(adj) < window + 1:
        return None
    rets = adj[-(window + 1):]
    daily = rets[1:] / rets[:-1] - 1.0
    if len(daily) < 2:
        return None
    return float(np.std(daily, ddof=1) * np.sqrt(TRADING_DAYS))


def _drawdown(adj: np.ndarray, window: int):
    """Max peak-to-trough drawdown over the trailing ``window`` rows (<= 0).

    Uses whatever rows exist if fewer than ``window`` are available (a drawdown
    is still meaningful on a shorter sample); returns None only with < 2 rows.
    """
    if len(adj) < 2:
        return None
    tail = adj[-window:] if len(adj) >= window else adj
    running_max = np.maximum.accumulate(tail)
    dd = tail / running_max - 1.0
    return float(dd.min())


def _sma(adj: np.ndarray, window: int):
    """Simple moving average of the last ``window`` closes, or None if short."""
    if len(adj) < window:
        return None
    return float(np.mean(adj[-window:]))


def compute_signals(frame: pd.DataFrame) -> dict:
    """Compute the technical signal set for one ticker's sliced price frame.

    ``frame`` must already be sliced to ``asof`` (rows dated <= asof) and sorted
    by date ascending; it is treated read-only. Returns a dict of signals with
    ``None`` for any signal whose lookback is not satisfied (never fabricated).

    This is a pure function on an in-memory frame and is the test seam for the
    numeric hand-checks; the evidence pack itself carries only the C4 fields.
    """
    adj = frame["adj_close"].to_numpy(dtype=float)
    n = len(adj)
    last_close = float(adj[-1]) if n else None

    sma50 = _sma(adj, SMA_FAST)
    sma200 = _sma(adj, SMA_SLOW)

    if sma50 is None or sma200 is None:
        sma_cross = None
    elif sma50 > sma200:
        sma_cross = "golden"
    elif sma50 < sma200:
        sma_cross = "death"
    else:
        sma_cross = "flat"

    return {
        "n_rows": n,
        "last_close": last_close,
        "momentum_63d": _total_return(adj, MOM_SHORT),
        "momentum_126d": _total_return(adj, MOM_LONG),
        "vol_20d_annualized": _realized_vol(adj, VOL_WINDOW),
        "drawdown_252d": _drawdown(adj, DD_WINDOW),
        "sma50": sma50,
        "sma200": sma200,
        "close_vs_sma50": (None if sma50 is None else bool(last_close >= sma50)),
        "close_vs_sma200": (None if sma200 is None else bool(last_close >= sma200)),
        "sma_cross": sma_cross,
    }


def _pct(x) -> str:
    return "n/a" if x is None else f"{x * 100:+.1f}%"


def _summarize(ticker: str, sig: dict) -> str:
    """One short sentence for B's analyst, or the insufficient-history marker."""
    if sig["n_rows"] == 0 or sig["sma200"] is None:
        # Flagship 200-day trend unavailable -> flag the item.
        return INSUFFICIENT_TEXT

    trend_bits = []
    if sig["close_vs_sma50"] is not None:
        trend_bits.append("above" if sig["close_vs_sma50"] else "below")
        trend_bits.append("SMA50")
    if sig["close_vs_sma200"] is not None:
        side = "above" if sig["close_vs_sma200"] else "below"
        trend_bits.append(f"and {side} SMA200")
    trend_txt = "close " + " ".join(trend_bits) if trend_bits else ""

    cross_txt = {
        "golden": "golden cross (SMA50>SMA200)",
        "death": "death cross (SMA50<SMA200)",
        "flat": "flat SMA50/SMA200",
    }.get(sig["sma_cross"], "")

    return (
        f"{ticker}: 63d momentum {_pct(sig['momentum_63d'])}, "
        f"126d {_pct(sig['momentum_126d'])}; "
        f"20d annualized vol {_pct(sig['vol_20d_annualized'])}; "
        f"252d drawdown {_pct(sig['drawdown_252d'])}; "
        f"{trend_txt}; {cross_txt}."
    )


def build_technical_evidence(
    asof: AsOf,
    universe: Iterable[str],
    store_dir: str = "data/prices",
) -> dict:
    """Build the technical evidence pack for ``universe`` at ``asof`` (C4).

    Returns the pack dict; the caller writes the file. All price data is read
    via ``pit.slice_store`` (the only data door), so nothing in the pack is
    dated after ``asof``. One item per universe ticker; item id is
    ``pit.px_id(ticker, asof)`` and item date is the asof ISO day.
    """
    universe = list(universe)
    asof_iso = _asof_iso(asof)

    sliced = pit.slice_store(asof, store_dir)  # guarded: no row dated > asof

    # data_horizon.px = latest actual trading day present on or before asof.
    if len(sliced):
        horizon = sliced["date"].max()
        horizon_iso = horizon.date().isoformat()
    else:
        horizon_iso = asof_iso

    items = []
    for ticker in universe:
        tdf = (
            sliced[sliced["ticker"] == ticker]
            .sort_values("date")
            .reset_index(drop=True)
        )
        if len(tdf) == 0:
            text = INSUFFICIENT_TEXT
        else:
            sig = compute_signals(tdf)
            text = _summarize(ticker, sig)
        items.append(
            {
                "id": pit.px_id(ticker, asof_iso),
                "ticker": ticker,
                "date": asof_iso,
                "text": text,
            }
        )

    return {
        "analyst": "technical",
        "asof": asof_iso,
        "data_horizon": {"px": horizon_iso},
        "items": items,
    }
