"""T5 — Committed price store builder for Person A's data lane.

Fetches daily adjusted prices (Yahoo Finance, via ``src.data.prices``) for the
universe + SPY (+ ^IRX, non-critical) and writes them to disk as the committed
price store defined by contract C2:

    data/prices/<TICKER>.csv   one ticker, canonical C1 columns, committed
    data/prices/_manifest.json { generated, source, tickers, date_min,
                                 date_max, rows_per_ticker }

This module only PRODUCES data. It imports ``prices.py`` (the source of truth
for fetching + the canonical schema) and never re-implements it.

Design decisions (locked with A, 2026-10-23):
  - range_ = "2y": gives >200 trading rows before the 2026-01-30 cutoff AND
    coverage through END 2026-10-16. Verified empirically, not assumed.
  - ^IRX is fetched but NON-CRITICAL (risk-free stays 0 for v1). Its failure
    warns; a universe/SPY failure FAILS HARD (a missing universe ticker breaks
    equal-weight, so we want to know immediately).
  - CSV: canonical C1 columns in order, dates ISO YYYY-MM-DD, full float
    precision (no rounding — reproducible diffs).
  - Filenames are sanitized (``^`` -> ``_``) so ``^IRX`` is written as
    ``_IRX.csv``; the CSV's ``ticker`` column and the manifest keep the true
    ``^IRX`` symbol. Only the on-disk filename is sanitized.
  - Manifest date_min/date_max span ALL written tickers (incl. ^IRX).

CLI:  python -m src.data.build_store
"""
from __future__ import annotations

import datetime as dt
import json
import os
from typing import Iterable

import pandas as pd

from src.data.prices import CANONICAL_COLUMNS, fetch_prices

# ---- Defaults (overridable via config.yaml at the CLI layer) --------------
DEFAULT_UNIVERSE = ["AAPL", "MSFT", "NVDA", "AMZN", "XOM", "JNJ", "PG", "CAT", "NEE", "KO"]
DEFAULT_EXTRA = ["SPY"]              # critical: baseline, must not fail
DEFAULT_NONCRITICAL = ["^IRX"]       # risk-free proxy; failure only warns
DEFAULT_STORE_DIR = "data/prices"
DEFAULT_RANGE = "2y"
DEFAULT_ASOF = "2026-01-30"
DEFAULT_END = "2026-10-16"

# Coverage gate: every CRITICAL ticker must clear these.
MIN_ROWS_BEFORE_CUTOFF = 200


def sanitize_filename(ticker: str) -> str:
    """Map a ticker symbol to a filesystem-safe CSV stem.

    ``^`` (used by index symbols like ^IRX) is awkward in shells, so it is
    replaced with ``_``. The true ticker is preserved in the CSV body and the
    manifest; only the filename changes.
    """
    return ticker.replace("^", "_")


def _coverage(df: pd.DataFrame, asof: str, end: str) -> dict:
    """Compute coverage facts for one ticker's canonical frame."""
    asof_ts = pd.Timestamp(asof)
    end_ts = pd.Timestamp(end)
    dates = df["date"]
    return {
        "rows": int(len(df)),
        "date_min": dates.min().date().isoformat() if len(df) else None,
        "date_max": dates.max().date().isoformat() if len(df) else None,
        "rows_before_cutoff": int((dates < asof_ts).sum()),
        "through_end": bool(len(df) and dates.max() >= end_ts),
    }


def _check_critical(ticker: str, cov: dict, asof: str, end: str) -> None:
    """Fail hard if a critical ticker doesn't clear the coverage gate."""
    problems = []
    if cov["rows_before_cutoff"] < MIN_ROWS_BEFORE_CUTOFF:
        problems.append(
            f"only {cov['rows_before_cutoff']} rows before {asof} "
            f"(need >= {MIN_ROWS_BEFORE_CUTOFF})"
        )
    if not cov["through_end"]:
        problems.append(f"data stops at {cov['date_max']} (need >= {end})")
    if problems:
        raise RuntimeError(
            f"Coverage check FAILED for critical ticker {ticker!r}: "
            + "; ".join(problems)
        )


def build_store(
    universe: Iterable[str] = DEFAULT_UNIVERSE,
    extra: Iterable[str] = DEFAULT_EXTRA,
    noncritical: Iterable[str] = DEFAULT_NONCRITICAL,
    store_dir: str = DEFAULT_STORE_DIR,
    range_: str = DEFAULT_RANGE,
    asof: str = DEFAULT_ASOF,
    end: str = DEFAULT_END,
) -> dict:
    """Build the committed price store and return the manifest dict.

    Critical tickers = ``universe + extra`` (SPY). A fetch failure OR a failed
    coverage check on any critical ticker raises immediately (fail hard).
    ``noncritical`` tickers (^IRX) only warn on failure.
    """
    universe = list(universe)
    extra = list(extra)
    noncritical = list(noncritical)
    critical = universe + extra

    os.makedirs(store_dir, exist_ok=True)

    written: list[str] = []          # true ticker symbols written to disk
    rows_per_ticker: dict[str, int] = {}
    coverage: dict[str, dict] = {}
    global_min: pd.Timestamp | None = None
    global_max: pd.Timestamp | None = None

    def _write(ticker: str, df: pd.DataFrame) -> None:
        nonlocal global_min, global_max
        path = os.path.join(store_dir, f"{sanitize_filename(ticker)}.csv")
        out = df[CANONICAL_COLUMNS].copy()
        # ISO YYYY-MM-DD dates; full float precision (no rounding).
        out["date"] = out["date"].dt.strftime("%Y-%m-%d")
        out.to_csv(path, index=False)
        written.append(ticker)
        rows_per_ticker[ticker] = int(len(df))
        dmin, dmax = df["date"].min(), df["date"].max()
        global_min = dmin if global_min is None else min(global_min, dmin)
        global_max = dmax if global_max is None else max(global_max, dmax)

    # --- Critical tickers: fetch + gate + write, fail hard on any problem ---
    for ticker in critical:
        try:
            df = fetch_prices(ticker, range_=range_)
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(
                f"Fetch FAILED for critical ticker {ticker!r}: {e}"
            ) from e
        cov = _coverage(df, asof, end)
        _check_critical(ticker, cov, asof, end)
        coverage[ticker] = cov
        _write(ticker, df)

    # --- Non-critical tickers: fetch + write, warn (don't raise) on failure --
    for ticker in noncritical:
        try:
            df = fetch_prices(ticker, range_=range_)
            cov = _coverage(df, asof, end)
            coverage[ticker] = cov
            _write(ticker, df)
        except Exception as e:  # noqa: BLE001
            print(f"WARN: non-critical ticker {ticker!r} failed to fetch: {e}")

    manifest = {
        "generated": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source": "yahoo",
        "tickers": written,
        "date_min": global_min.date().isoformat() if global_min is not None else None,
        "date_max": global_max.date().isoformat() if global_max is not None else None,
        "rows_per_ticker": rows_per_ticker,
    }
    manifest_path = os.path.join(store_dir, "_manifest.json")
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")

    # Attach coverage (not persisted in the manifest file) for the CLI summary.
    manifest["_coverage"] = coverage
    manifest["_critical"] = critical
    return manifest


def _load_config(path: str = "config.yaml") -> dict:
    """Best-effort read of config.yaml for universe/asof/end (read-only)."""
    try:
        import yaml  # type: ignore
        with open(path) as f:
            return yaml.safe_load(f) or {}
    except Exception:  # noqa: BLE001 - fall back to module defaults
        return {}


def main() -> None:
    cfg = _load_config()
    universe = cfg.get("universe", DEFAULT_UNIVERSE)
    asof = str(cfg.get("asof", DEFAULT_ASOF))
    end = str(cfg.get("end", DEFAULT_END))

    manifest = build_store(universe=universe, asof=asof, end=end)

    coverage = manifest.pop("_coverage", {})
    critical = set(manifest.pop("_critical", []))

    print("=== _manifest.json ===")
    print(json.dumps(manifest, indent=2))

    print("\n=== coverage (asof={}, end={}) ===".format(asof, end))
    for ticker in manifest["tickers"]:
        cov = coverage.get(ticker, {})
        tag = "CRITICAL" if ticker in critical else "non-crit"
        ok = cov.get("rows_before_cutoff", 0) >= MIN_ROWS_BEFORE_CUTOFF and cov.get("through_end")
        status = "OK" if ok else ("OK*" if ticker not in critical else "FAIL")
        print(
            f"{ticker:<6} [{tag}] {cov.get('rows', 0):>4} rows | "
            f"{cov.get('date_min')} -> {cov.get('date_max')} | "
            f"pre-cutoff={cov.get('rows_before_cutoff', 0):>4} | "
            f"through_end={cov.get('through_end')} | {status}"
        )
    print("\n(* non-critical ^IRX is not gated; risk-free stays 0 for v1)")


if __name__ == "__main__":
    main()
