"""Geopolitics evidence pack (owner C).

Trade, sanctions, conflict and policy events relevant to the universe, each with
a dated source published on or before the cutoff. Built from the curated dated
event log (events.py); when GDELT serves, a market-wide conflict-intensity read
is added on top. Each event names the tickers with direct exposure so the
geopolitics analyst can translate a theme into per-name views.

Evidence IDs:
  event:<theme>            a dated, sourced event with ticker exposure
  gdelt:<theme>:<date>     optional GDELT conflict-intensity read (market-wide)

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


def _event_item(ev, universe):
    """One evidence item from a dated event row. Restricts exposure to universe tickers."""
    exposed = ev["tickers"]
    if exposed == ["ALL"] or exposed == "ALL":
        ticker = "ALL"
        who = "market-wide"
    else:
        inuni = [t for t in exposed if t in universe]
        if not inuni:
            return None
        ticker = inuni[0] if len(inuni) == 1 else "ALL"
        who = ", ".join(inuni)
    text = f"[{ev['theme']}] {ev['text']} Exposure: {who}. Source: {ev['source']} ({ev['date']})."
    return {"id": f"event:{ev['theme']}", "ticker": ticker, "date": ev["date"], "text": text}


def _gdelt_conflict_item(asof, start, end):
    """Optional market-wide conflict-intensity read from GDELT, or None if unavailable."""
    series = gdelt.tone_timeline("conflict OR sanctions OR tariffs", start, end)
    if not series:
        return None
    vols = [p["volume"] for p in series]
    if not vols:
        return None
    recent = sum(vols[-14:]) / max(1, len(vols[-14:]))
    base = sum(vols) / len(vols)
    pct = (recent / base - 1) * 100 if base else 0.0
    last = series[-1]["date"]
    text = (f"GDELT conflict/sanctions/tariff coverage in the two weeks to {asof} is {pct:+.0f}% "
            f"versus the {WINDOW_DAYS}-day average, a market-wide geopolitical-intensity read.")
    return {"id": f"gdelt:CONFLICT:{last}", "ticker": "ALL", "date": last, "text": text}


def build_pack(universe, asof):
    """Build the geopolitics evidence pack from the dated event log, plus GDELT if available."""
    asof = str(asof)
    end = datetime.date.fromisoformat(asof)
    start = (end - datetime.timedelta(days=WINDOW_DAYS)).isoformat()

    items = []
    for ev in events.geo_events(asof):
        item = _event_item(ev, universe)
        if item:
            items.append(item)

    source = "events"
    if gdelt.available():
        gi = _gdelt_conflict_item(asof, start, asof)
        if gi:
            items.append(gi)
            source = "events+gdelt"

    horizon = max((i["date"] for i in items), default=asof)
    return {
        "analyst": "geopolitics",
        "asof": asof,
        "source": source,  # "events" or "events+gdelt"
        "data_horizon": {"events": horizon},
        "items": items,
    }


def write_pack(path, universe, asof):
    pack = build_pack(universe, asof)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(pack, indent=2))
    return pack


__all__ = ["build_pack", "write_pack"]
