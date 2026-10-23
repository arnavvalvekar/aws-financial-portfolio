"""Point-in-time market regime-fragility evidence.

This module deliberately measures *current* crash risk at ``asof`` rather than
predicting a future crash.  Regular prices enter only through ``src.pit``.  The
optional ``_VIX.csv`` is a non-ticker auxiliary file, so it is loaded directly
and immediately filtered to the inclusive cutoff before its latest observation
is used.

Public API (C8)::

    build_regime_evidence(asof, universe, store_dir="data/prices") -> dict

``compute_regime`` is the pure numeric seam used by tests.  Its returned
``components`` values are all in [0, 1] and are the values blended into the
score.  Raw drawdown, volatility ratio, and VIX level are also returned for
an auditable evidence sentence.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Iterable, Mapping, Union

import numpy as np
import pandas as pd

from src import pit

AsOf = Union[str, dt.date, pd.Timestamp]

TRADING_DAYS = 252
DRAWDOWN_WINDOW = 252
VOL_WINDOW = 20
SMA_WINDOW = 200

# Typical descriptive VIX landmarks: below 15 is calm and 40+ is stressed.
VIX_CALM = 15.0
VIX_STRESSED = 40.0


def _asof_timestamp(asof: AsOf) -> pd.Timestamp:
    """Normalise ``asof`` to the tz-naive timestamp used by :mod:`src.pit`."""
    ts = pd.Timestamp(asof)
    if ts.tzinfo is not None:
        ts = ts.tz_convert(None) if ts.tz is not None else ts.tz_localize(None)
    return ts


def _asof_iso(asof: AsOf) -> str:
    return _asof_timestamp(asof).date().isoformat()


def _clip01(value: float) -> float:
    return float(np.clip(value, 0.0, 1.0))


def _adj_close(frame: pd.DataFrame) -> np.ndarray:
    """Return finite adjusted closes from an already point-in-time frame."""
    if frame.empty or "adj_close" not in frame.columns:
        return np.array([], dtype=float)
    values = frame.sort_values("date")["adj_close"].to_numpy(dtype=float)
    return values[np.isfinite(values)]


def _market_drawdown(spy_frame: pd.DataFrame) -> tuple[float | None, float | None]:
    """Return (signed drawdown, non-negative risk component)."""
    adj = _adj_close(spy_frame)
    if not len(adj):
        return None, None
    tail = adj[-DRAWDOWN_WINDOW:]
    peak = float(np.max(tail))
    if peak <= 0:
        return None, None
    signed = float(adj[-1] / peak - 1.0)
    return signed, _clip01(-signed)


def _volatility_series(adj: np.ndarray) -> np.ndarray:
    """Annualised rolling VOL_WINDOW volatility, in chronological order."""
    if len(adj) < VOL_WINDOW + 1:
        return np.array([], dtype=float)
    values = []
    for end in range(VOL_WINDOW, len(adj)):
        window = adj[end - VOL_WINDOW : end + 1]
        daily = window[1:] / window[:-1] - 1.0
        if len(daily) >= 2 and np.all(np.isfinite(daily)):
            values.append(float(np.std(daily, ddof=1) * np.sqrt(TRADING_DAYS)))
    return np.asarray(values, dtype=float)


def _volatility_risk(
    spy_frame: pd.DataFrame,
) -> tuple[float | None, float | None, float | None]:
    """Return (current annualised vol, raw spike ratio, risk component).

    The ratio is compared with the median of the trailing 252 available
    rolling-vol observations.  A ratio of 1 is baseline (zero spike risk), and
    a ratio at least 2 is capped at one.  This keeps the component bounded while
    retaining the meaning of a volatility *spike*.
    """
    series = _volatility_series(_adj_close(spy_frame))
    if not len(series):
        return None, None, None
    current = float(series[-1])
    baseline_values = series[-DRAWDOWN_WINDOW:]
    baseline = float(np.median(baseline_values))
    if not np.isfinite(baseline) or baseline <= 0:
        return current, None, None
    ratio = float(current / baseline)
    return current, ratio, _clip01(ratio - 1.0)


def _breadth_component(
    ticker_frames: Mapping[str, pd.DataFrame],
) -> tuple[float | None, dict[str, bool | None]]:
    """Return fraction below SMA200 and each ticker's trend-break state."""
    states: dict[str, bool | None] = {}
    for ticker, frame in ticker_frames.items():
        adj = _adj_close(frame)
        if len(adj) < SMA_WINDOW:
            states[ticker] = None
            continue
        sma = float(np.mean(adj[-SMA_WINDOW:]))
        states[ticker] = bool(adj[-1] < sma)

    known = [value for value in states.values() if value is not None]
    if not known:
        return None, states
    return float(sum(known) / len(known)), states


def _vix_component(
    vix_frame: pd.DataFrame | None,
) -> tuple[float | None, float | None]:
    """Return (latest VIX level, bounded VIX risk component)."""
    if vix_frame is None or vix_frame.empty:
        return None, None
    ordered = vix_frame.sort_values("date")
    column = "adj_close" if "adj_close" in ordered else "close"
    if column not in ordered:
        return None, None
    values = pd.to_numeric(ordered[column], errors="coerce").dropna()
    if values.empty:
        return None, None
    level = float(values.iloc[-1])
    component = _clip01((level - VIX_CALM) / (VIX_STRESSED - VIX_CALM))
    return level, component


def _coerce_inputs(
    frame: pd.DataFrame,
    universe: Iterable[str] | Mapping[str, pd.DataFrame] | pd.DataFrame | None,
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    """Accept the canonical sliced frame form and convenient test forms.

    The normal/build form is ``compute_regime(sliced_prices, universe)``.  For
    focused unit tests, a single SPY frame plus a mapping of ticker frames is
    also accepted.  Both forms are expected to have already passed through
    ``pit.slice``; the public builder is responsible for that guard.
    """
    if "ticker" in frame.columns:
        spy = frame[frame["ticker"] == "SPY"].sort_values("date").copy()
        if isinstance(universe, Mapping):
            tickers = {
                str(ticker): value.sort_values("date").copy()
                for ticker, value in universe.items()
            }
        elif isinstance(universe, pd.DataFrame):
            tickers = {
                str(ticker): group.sort_values("date").copy()
                for ticker, group in universe.groupby("ticker")
            }
        else:
            names = list(universe or [])
            tickers = {
                ticker: frame[frame["ticker"] == ticker]
                .sort_values("date")
                .copy()
                for ticker in names
            }
        return spy, tickers

    spy = frame.sort_values("date").copy()
    if isinstance(universe, Mapping):
        tickers = {
            str(ticker): value.sort_values("date").copy()
            for ticker, value in universe.items()
        }
    elif isinstance(universe, pd.DataFrame) and "ticker" in universe.columns:
        tickers = {
            str(ticker): group.sort_values("date").copy()
            for ticker, group in universe.groupby("ticker")
        }
    else:
        tickers = {}
    return spy, tickers


def compute_regime(
    frame: pd.DataFrame,
    universe: Iterable[str] | Mapping[str, pd.DataFrame] | pd.DataFrame | None = None,
    vix_frame: pd.DataFrame | None = None,
) -> dict:
    """Compute regime components from already-sliced price frames.

    ``frame`` is normally the canonical result of ``pit.slice_store`` and
    ``universe`` is the ticker list.  No filtering or file access occurs here;
    that makes the function a deterministic unit-test seam.  Components are
    equal-weighted over the available signals, so a missing VIX degrades to the
    three required price components.
    """
    spy, ticker_frames = _coerce_inputs(frame, universe)
    drawdown_raw, drawdown_component = _market_drawdown(spy)
    current_vol, vol_ratio, vol_component = _volatility_risk(spy)
    breadth, trend_breaks = _breadth_component(ticker_frames)
    vix_level, vix_component = _vix_component(vix_frame)

    available = {
        "market_drawdown": drawdown_component,
        "volatility_spike": vol_component,
        "below_sma200": breadth,
    }
    if vix_component is not None:
        available["vix"] = vix_component
    numeric = [value for value in available.values() if value is not None]
    score = float(np.mean(numeric)) if numeric else 0.0
    score = _clip01(score)
    if score < 0.33:
        band = "calm"
    elif score <= 0.66:
        band = "elevated"
    else:
        band = "stressed"

    return {
        "market_drawdown": drawdown_raw,
        "market_drawdown_component": drawdown_component,
        "current_vol_20d_annualized": current_vol,
        "vol_spike_ratio": vol_ratio,
        "volatility_spike_component": vol_component,
        "below_sma200_fraction": breadth,
        "trend_breaks": trend_breaks,
        "vix_level": vix_level,
        "vix_component": vix_component,
        "components": available,
        "crash_risk_score": score,
        "band": band,
    }


def _load_vix_until(asof: AsOf, store_dir: str | Path) -> pd.DataFrame | None:
    """Load only the point-in-time portion of the optional VIX CSV.

    ``_VIX.csv`` is auxiliary and intentionally skipped by ``pit.load_prices``.
    The committed files are commonly headerless C1 rows, but a header-bearing
    file is accepted as well.  Filtering happens before any values are used,
    and the defensive check makes an accidental future row fail loudly.
    """
    path = Path(store_dir) / "_VIX.csv"
    if not path.is_file():
        return None

    raw = pd.read_csv(path, header=None)
    columns = ["ticker", "date", "open", "high", "low", "close", "adj_close", "volume"]
    if len(raw.columns) >= len(columns) and str(raw.iloc[0, 0]).lower() == "ticker":
        raw = raw.iloc[1:].reset_index(drop=True)
    if len(raw.columns) < len(columns):
        raise ValueError(f"{path} does not have the canonical VIX columns")
    raw = raw.iloc[:, : len(columns)].copy()
    raw.columns = columns
    raw["date"] = pd.to_datetime(raw["date"], errors="coerce").dt.tz_localize(None)
    raw = raw[raw["date"].notna()].copy()
    cutoff = _asof_timestamp(asof)
    sliced = raw[raw["date"] <= cutoff].copy().reset_index(drop=True)
    later = sliced[sliced["date"] > cutoff]
    if not later.empty:
        raise ValueError("point-in-time violation in _VIX.csv")
    for column in ("close", "adj_close"):
        raw_values = pd.to_numeric(sliced[column], errors="coerce")
        sliced[column] = raw_values.astype(float)
    return sliced


def _fmt(value: float | None, multiplier: float = 1.0) -> str:
    return "n/a" if value is None else f"{value * multiplier:.4f}"


def _summary_text(result: dict, horizon: str, asof_iso: str) -> str:
    components = result["components"]
    component_text = ", ".join(
        f"{name}={_fmt(value)}" for name, value in components.items()
    )
    return (
        f"Regime fragility at {asof_iso} (latest price {horizon}): "
        f"crash_risk_score={result['crash_risk_score']:.4f}; "
        f"band={result['band']}; components[{component_text}]; "
        f"drawdown={_fmt(result['market_drawdown'], 100)}%; "
        f"vol_spike_ratio={_fmt(result['vol_spike_ratio'])}; "
        f"vix={_fmt(result['vix_level'])}."
    )


def build_regime_evidence(
    asof: AsOf,
    universe: Iterable[str],
    store_dir: str = "data/prices",
) -> dict:
    """Build the C4 regime evidence pack using only rows at or before ``asof``."""
    names = [str(ticker) for ticker in universe]
    asof_iso = _asof_iso(asof)
    sliced = pit.slice_store(asof, store_dir)
    vix = _load_vix_until(asof, store_dir)
    result = compute_regime(sliced, names, vix)

    if sliced.empty:
        horizon = asof_iso
    else:
        horizon = pd.to_datetime(sliced["date"]).max().date().isoformat()

    items = [
        {
            "id": f"regime:{asof_iso}",
            "ticker": "SPY",
            "date": asof_iso,
            "text": _summary_text(result, horizon, asof_iso),
        }
    ]
    for ticker in names:
        frame = sliced[sliced["ticker"] == ticker].sort_values("date")
        adj = _adj_close(frame)
        if len(adj) < SMA_WINDOW:
            text = f"{ticker}: insufficient history for 200-day SMA trend-break assessment."
        else:
            sma = float(np.mean(adj[-SMA_WINDOW:]))
            side = "below" if adj[-1] < sma else "above or at"
            text = (
                f"{ticker}: close is {side} 200-day SMA "
                f"(close={adj[-1]:.4f}, sma200={sma:.4f}); "
                f"trend_break={side == 'below'}."
            )
        items.append(
            {
                "id": pit.px_id(ticker, asof_iso),
                "ticker": ticker,
                "date": asof_iso,
                "text": text,
            }
        )

    return {
        "analyst": "regime",
        "asof": asof_iso,
        "data_horizon": {"px": horizon},
        "items": items,
    }
