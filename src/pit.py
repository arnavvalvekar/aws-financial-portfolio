"""Point-in-time guard — the ONLY door through which agents and evidence read
price data (contract C3).

The cutoff is a one-way valve: an analyst or evidence module must never see a
row dated after the `asof` it is reasoning at. Everything that feeds an agent
goes through `slice`/`slice_store` here, so the no-look-ahead rule lives in one
place and is enforced the same way everywhere. (The backtest is the single
exception: it scores the post-cutoff window and reads later prices directly,
not through this module.)

Public API (stable — C3):
    load_prices(store_dir="data/prices") -> DataFrame
        Read every <TICKER>.csv in the store (skipping "_"-prefixed files such
        as _IRX.csv and _manifest.json) into one canonical C1 frame.
    slice(df, asof) -> DataFrame
        Return a copy with only rows dated on or before `asof` (inclusive).
    slice_store(asof, store_dir="data/prices") -> DataFrame
        Convenience: load_prices(store_dir) then slice(..., asof).
    px_id(ticker, date) -> "px:<TICKER>:<date-iso>"
        Canonical price evidence ID (SCHEMAS.md). Built here so the format
        lives in one place; evidence modules call it.

Design notes:
    - `asof` is INCLUSIVE (`date <= asof`): agents see the cutoff day itself,
      matching README's "on or before the cutoff".
    - `slice` filters by design, then runs a defensive self-check and RAISES if
      any surviving row is dated after `asof`. That branch only trips on a bug;
      it never silently drops data.
    - `asof` accepts str / datetime.date / pandas.Timestamp.
    - Row-based only: no trading-calendar / holiday awareness. "Whatever rows
      exist on or before asof" is the contract — vendor- and calendar-agnostic.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Union

import pandas as pd

from src.data.prices import CANONICAL_COLUMNS

AsOf = Union[str, dt.date, pd.Timestamp]

DEFAULT_STORE_DIR = "data/prices"


def _to_timestamp(asof: AsOf) -> pd.Timestamp:
    """Normalise any accepted `asof` type to a tz-naive midnight Timestamp.

    A bare date or ISO string becomes midnight of that day; since the store's
    dates are normalised to midnight too, `date <= asof` keeps the cutoff day.
    """
    ts = pd.Timestamp(asof)
    if ts.tzinfo is not None:
        ts = ts.tz_convert(None) if ts.tz is not None else ts.tz_localize(None)
    return ts


def load_prices(store_dir: str | Path = DEFAULT_STORE_DIR) -> pd.DataFrame:
    """Load the on-disk price store into one canonical C1 frame.

    Reads every ``<TICKER>.csv`` in ``store_dir``. Files whose name starts with
    an underscore (e.g. ``_IRX.csv``, ``_manifest.json``) are IGNORED — they are
    not universe tickers. The result is the canonical long-format frame:
    ``ticker,date,open,high,low,close,adj_close,volume`` sorted by
    ``(ticker, date)``.
    """
    store = Path(store_dir)
    if not store.is_dir():
        raise FileNotFoundError(f"price store not found: {store}")

    csv_paths = sorted(
        p for p in store.glob("*.csv") if not p.name.startswith("_")
    )
    if not csv_paths:
        raise FileNotFoundError(f"no ticker CSVs found in {store}")

    frames = []
    for path in csv_paths:
        frame = pd.read_csv(path)
        missing = [c for c in CANONICAL_COLUMNS if c not in frame.columns]
        if missing:
            raise ValueError(f"{path.name} missing canonical columns: {missing}")
        frame = frame[CANONICAL_COLUMNS].copy()
        frame["date"] = pd.to_datetime(frame["date"]).dt.tz_localize(None)
        for col in ("open", "high", "low", "close", "adj_close"):
            frame[col] = frame[col].astype(float)
        frame["volume"] = frame["volume"].astype("Int64")
        frame["ticker"] = frame["ticker"].astype(str)
        frames.append(frame)

    df = pd.concat(frames, ignore_index=True)
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)
    return df[CANONICAL_COLUMNS]


def slice(df: pd.DataFrame, asof: AsOf) -> pd.DataFrame:  # noqa: A001 - C3 name
    """Return rows dated on or before ``asof`` (inclusive).

    Never mutates ``df`` — returns a filtered copy. After filtering, performs a
    defensive self-check: if any surviving row has ``date > asof`` the function
    RAISES ``ValueError``. That can only happen through a bug (bad comparison,
    tz mix-up); by design the filter already removes later rows.
    """
    cutoff = _to_timestamp(asof)
    if "date" not in df.columns:
        raise ValueError("frame has no 'date' column; not a canonical price frame")

    mask = df["date"] <= cutoff
    out = df[mask].copy().reset_index(drop=True)

    _assert_no_future(out, cutoff)
    return out


def _assert_no_future(df: pd.DataFrame, cutoff: pd.Timestamp) -> None:
    """Defensive guard: raise if any row is dated after ``cutoff``.

    Factored out so the no-look-ahead invariant can be asserted directly (and
    unit-tested) independent of the filtering in ``slice``.
    """
    if df.empty:
        return
    later = df[df["date"] > cutoff]
    if len(later) > 0:
        bad = sorted({d.date().isoformat() for d in later["date"]})
        raise ValueError(
            f"point-in-time violation: {len(later)} row(s) dated after "
            f"{cutoff.date().isoformat()} survived the slice: {bad}"
        )


def slice_store(
    asof: AsOf, store_dir: str | Path = DEFAULT_STORE_DIR
) -> pd.DataFrame:
    """Load the store and slice it to ``asof`` in one call (C3 convenience)."""
    return slice(load_prices(store_dir), asof)


def px_id(ticker: str, date: AsOf) -> str:
    """Build the canonical price evidence ID ``px:<TICKER>:<date-iso>``.

    Ticker is upper-cased; date is rendered as ISO ``YYYY-MM-DD``. Accepts a
    str / date / Timestamp for ``date`` (SCHEMAS.md: ``px:<TICKER>:<date>``).
    """
    iso = _to_timestamp(date).date().isoformat()
    return f"px:{str(ticker).upper()}:{iso}"
