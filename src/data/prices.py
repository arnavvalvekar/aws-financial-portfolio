"""Daily price loader for Person A's data lane.

DATA SOURCE DECISION (probed 2026-10-23 from the workshop network):
  - Stooq (README's first choice) is BLOCKED behind a JavaScript anti-bot
    wall. Every variant (.com/.pl/http) returns HTTP 200 but serves a JS
    crypto-challenge page, not CSV. Plain downloads are unusable.
  - FRED's web CSV host (fred.stlouisfed.org) is unreachable (HTTP 000);
    the API host needs a 32-char key we don't have. Macro is NOT on the
    critical path (README allows risk-free = zero), so prices come first.
  - Yahoo Finance chart API (query1/query2.finance.yahoo.com) IS reachable,
    returns clean JSON OHLC with adjusted close, and covers the full scored
    window plus >200 days of pre-cutoff history. We use it for prices.

The loader normalises Yahoo's JSON into one canonical long-format frame so
the rest of the lane (pit.slice, technical evidence, backtest) never sees a
vendor-specific shape. If a Stooq/Kaggle path opens up later, only this file
changes.

Canonical schema (one row per ticker per trading day):
    ticker:   str
    date:     datetime64[ns]  (trading day, tz-naive, midnight)
    open high low close:  float  (raw OHLC)
    adj_close: float             (split/dividend adjusted; used for returns)
    volume:    Int64

Returns are always computed from adj_close so the portfolio and both
baselines use the same adjusted series (README: "same adjusted price series").
"""
from __future__ import annotations

import time
import datetime as dt
from typing import Iterable

import pandas as pd
import requests

YAHOO_HOSTS = (
    "https://query1.finance.yahoo.com",
    "https://query2.finance.yahoo.com",
)
_CHART_PATH = "/v8/finance/chart/{symbol}"
_HEADERS = {"User-Agent": "Mozilla/5.0 (aws-financial-portfolio hackathon)"}
_TIMEOUT = 20

CANONICAL_COLUMNS = [
    "ticker", "date", "open", "high", "low", "close", "adj_close", "volume",
]

# Yahoo symbol overrides. Universe tickers map 1:1; indices need a caret.
_SYMBOL_OVERRIDES = {
    "^IRX": "^IRX",  # 13-week T-bill, risk-free proxy if we want one
}


def _yahoo_symbol(ticker: str) -> str:
    return _SYMBOL_OVERRIDES.get(ticker, ticker)


def fetch_prices(
    ticker: str,
    start: str | dt.date | None = None,
    end: str | dt.date | None = None,
    range_: str = "2y",
    session: requests.Session | None = None,
    retries: int = 3,
) -> pd.DataFrame:
    """Fetch daily adjusted prices for one ticker from Yahoo Finance.

    If ``start``/``end`` are given, uses period1/period2 (inclusive).
    Otherwise falls back to the ``range_`` window (e.g. "2y").
    Returns a canonical frame sorted by date ascending.
    """
    symbol = _yahoo_symbol(ticker)
    params = {"interval": "1d", "events": "div,split"}
    if start is not None or end is not None:
        params["period1"] = _to_epoch(start, default=0)
        params["period2"] = _to_epoch(end, default=int(time.time()) + 86400)
    else:
        params["range"] = range_

    sess = session or requests.Session()
    last_err: Exception | None = None
    for attempt in range(retries):
        host = YAHOO_HOSTS[attempt % len(YAHOO_HOSTS)]
        url = host + _CHART_PATH.format(symbol=symbol)
        try:
            resp = sess.get(url, params=params, headers=_HEADERS, timeout=_TIMEOUT)
            resp.raise_for_status()
            payload = resp.json()
            return _parse_chart(ticker, payload)
        except Exception as e:  # noqa: BLE001 - retry any transient failure
            last_err = e
            time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"Yahoo fetch failed for {ticker!r}: {last_err}")


def _parse_chart(ticker: str, payload: dict) -> pd.DataFrame:
    chart = payload.get("chart", {})
    if chart.get("error"):
        raise RuntimeError(f"Yahoo error for {ticker}: {chart['error']}")
    result = chart["result"][0]
    timestamps = result.get("timestamp", [])
    quote = result["indicators"]["quote"][0]
    adj = (
        result["indicators"].get("adjclose", [{}])[0].get("adjclose")
        if result["indicators"].get("adjclose")
        else None
    )
    # Yahoo returns UTC epoch seconds at market open; normalise to the
    # calendar trading day (date only) so joins across tickers line up.
    dates = pd.to_datetime(pd.Series(timestamps), unit="s", utc=True)
    dates = dates.dt.tz_convert("America/New_York").dt.normalize().dt.tz_localize(None)

    frame = pd.DataFrame(
        {
            "ticker": ticker,
            "date": dates,
            "open": quote.get("open"),
            "high": quote.get("high"),
            "low": quote.get("low"),
            "close": quote.get("close"),
            "adj_close": adj if adj is not None else quote.get("close"),
            "volume": quote.get("volume"),
        }
    )
    # Drop rows Yahoo pads with nulls (holidays/half-days with no print).
    frame = frame.dropna(subset=["close"]).reset_index(drop=True)
    frame["volume"] = frame["volume"].astype("Int64")
    return frame[CANONICAL_COLUMNS].sort_values("date").reset_index(drop=True)


def fetch_many(
    tickers: Iterable[str],
    start: str | dt.date | None = None,
    end: str | dt.date | None = None,
    range_: str = "2y",
) -> pd.DataFrame:
    """Fetch several tickers and concatenate into one canonical frame."""
    sess = requests.Session()
    frames = [
        fetch_prices(t, start=start, end=end, range_=range_, session=sess)
        for t in tickers
    ]
    return pd.concat(frames, ignore_index=True)


def _to_epoch(value, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return int(value)
    d = pd.Timestamp(value)
    return int(d.tz_localize("UTC").timestamp()) if d.tzinfo is None else int(d.timestamp())
