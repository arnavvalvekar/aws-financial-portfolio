"""Sentiment evidence pack (owner C).

Media tone and article volume per ticker over the 90 days before the cutoff,
from GDELT when it serves, otherwise a dated qualitative fallback. One evidence
item per ticker so the sentiment analyst can give one view each; a ticker with
no usable signal becomes an explicit "insufficient data" note rather than a
fabricated number.

Evidence IDs:
  gdelt:<TICKER>:<date>     when built from GDELT tone (date = cutoff, the read's asof)
  event:sentiment:<TICKER>  qualitative fallback row

Pack schema matches SCHEMAS.md: {analyst, asof, data_horizon, items:[{id,ticker,date,text}]}.
Nothing is dated after asof by construction.

Public API:
  build_pack(universe, asof)        -> pack dict
  write_pack(path, universe, asof)  -> write and return the pack
"""

import datetime
import json
from pathlib import Path

from ..data import gdelt
from . import events

ROOT = Path(__file__).resolve().parents[2]
WINDOW_DAYS = 90

# Rough company-name queries so GDELT matches coverage of the firm, not the ticker.
NAMES = {
    "AAPL": "Apple", "MSFT": "Microsoft", "NVDA": "Nvidia", "AMZN": "Amazon",
    "XOM": "ExxonMobil", "JNJ": "Johnson & Johnson", "PG": "Procter & Gamble",
    "CAT": "Caterpillar", "NEE": "NextEra Energy", "KO": "Coca-Cola",
}


def _window(asof):
    end = datetime.date.fromisoformat(str(asof))
    start = end - datetime.timedelta(days=WINDOW_DAYS)
    return start.isoformat(), end.isoformat()


def _gdelt_item(ticker, asof, series):
    """Summarise a GDELT tone series into one evidence item, or None if empty."""
    if not series:
        return None
    tones = [p["tone"] for p in series]
    vols = [p["volume"] for p in series]
    avg_tone = sum(tones) / len(tones)
    total_vol = sum(vols)
    last = series[-1]
    trend = "improving" if len(tones) >= 2 and tones[-1] > tones[0] else \
            "deteriorating" if len(tones) >= 2 and tones[-1] < tones[0] else "flat"
    text = (f"Average media tone about {NAMES.get(ticker, ticker)} over the {WINDOW_DAYS} days to "
            f"{asof}: {avg_tone:+.2f} across {total_vol} articles ({len(series)} days of coverage), "
            f"tone {trend} into the cutoff (latest {last['tone']:+.2f}).")
    return {"id": f"gdelt:{ticker}:{asof}", "ticker": ticker, "date": str(asof), "text": text}


def _fallback_item(ticker, asof, note):
    text = f"{NAMES.get(ticker, ticker)}: {note} (qualitative read as of {asof}; GDELT tone unavailable)."
    return {"id": f"event:sentiment:{ticker}", "ticker": ticker, "date": str(asof), "text": text}


def build_pack(universe, asof):
    """Build the sentiment evidence pack. Uses GDELT when available, else the dated fallback."""
    asof = str(asof)
    start, end = _window(asof)
    items = []
    source = "fallback"
    horizon = None

    use_gdelt = gdelt.available()
    notes = events.sentiment_notes()
    for ticker in universe:
        item = None
        if use_gdelt:
            series = gdelt.tone_timeline(NAMES.get(ticker, ticker), start, end)
            item = _gdelt_item(ticker, asof, series)
            if item and series:
                source = "gdelt"
                last_date = series[-1]["date"]
                horizon = max(horizon, last_date) if horizon else last_date
        if item is None:  # GDELT off or empty for this ticker -> dated fallback
            note = notes.get(ticker, "no pre-cutoff sentiment signal in scope")
            item = _fallback_item(ticker, asof, note)
        items.append(item)

    if horizon is None:
        horizon = asof  # fallback rows are dated at the cutoff
    return {
        "analyst": "sentiment",
        "asof": asof,
        "source": source,  # "gdelt" or "fallback"; shown on the dashboard
        "data_horizon": {"gdelt" if source == "gdelt" else "events": horizon},
        "items": items,
    }


def write_pack(path, universe, asof):
    pack = build_pack(universe, asof)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(pack, indent=2))
    return pack


__all__ = ["build_pack", "write_pack"]
