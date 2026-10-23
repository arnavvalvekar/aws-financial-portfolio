"""GDELT access for sentiment and geopolitics evidence (owner C).

GDELT's DOC 2.0 API gives a tone timeline and article volume for a query over a
date window. We use it for the 90 days before the cutoff. Two realities shape
this module:

  1. Point-in-time. Every window ends at the cutoff; nothing dated after it is
     ever requested, so no post-cutoff news can leak in.
  2. GDELT throttles hard. It asks for one request every 5 seconds and returns
     HTTP 429 to high-traffic shared IPs (the workshop network hits this). So we
     rate-limit, cache every response to disk, and - when GDELT will not serve -
     fall back to a curated dated event log (events.py) where every row carries a
     real source published before the cutoff.

Public API:
  tone_timeline(query, start, end)  -> list of {date, tone, volume} or None on failure
  available()                       -> quick True/False probe (cached per process)

The evidence builders (sentiment.py, geo.py) decide GDELT-vs-fallback by checking
whether tone_timeline returns data; they never raise on a GDELT outage.
"""

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "gdelt"

_DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
USER_AGENT = os.environ.get("GDELT_USER_AGENT", "aws-financial-portfolio hackathon research")

_last_call = [0.0]
_MIN_INTERVAL = 5.2  # GDELT asks for <= 1 request / 5s; a little margin


def _throttle():
    wait = _MIN_INTERVAL - (time.time() - _last_call[0])
    if wait > 0:
        time.sleep(wait)


def _cache_key(params):
    import hashlib

    raw = json.dumps(params, sort_keys=True).encode()
    return hashlib.sha256(raw).hexdigest()[:24]


def _fetch(params, timeout=30):
    """One GDELT DOC request. Returns parsed JSON dict, or None on any failure
    (rate limit, non-JSON challenge page, network error). Never raises."""
    RAW.mkdir(parents=True, exist_ok=True)
    cache = RAW / f"doc_{_cache_key(params)}.json"
    if cache.exists():
        try:
            return json.loads(cache.read_text())
        except json.JSONDecodeError:
            pass  # a bad cache file; re-fetch below

    _throttle()
    url = _DOC_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, OSError):
        _last_call[0] = time.time()
        return None
    _last_call[0] = time.time()

    body = body.strip()
    # GDELT returns a plain-text throttle/challenge message (not JSON) when it
    # refuses. Detect that and treat it as "unavailable".
    if not body.startswith("{"):
        return None
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return None
    cache.write_text(json.dumps(data))
    return data


def tone_timeline(query, start, end):
    """Daily average tone and article volume for `query` between start and end (YYYY-MM-DD).

    Returns a list of {"date": "YYYY-MM-DD", "tone": float, "volume": int},
    or None if GDELT is unavailable. The window is clipped so nothing is ever
    requested after `end` (the cutoff).
    """
    params = {
        "query": query,
        "mode": "timelinetone",
        "startdatetime": start.replace("-", "") + "000000",
        "enddatetime": end.replace("-", "") + "000000",
        "format": "json",
    }
    tone = _fetch(params)
    vol_params = dict(params, mode="timelinevolraw")
    vol = _fetch(vol_params)
    if not tone or "timeline" not in tone or not tone["timeline"]:
        return None

    tseries = tone["timeline"][0].get("data", [])
    vmap = {}
    if vol and vol.get("timeline"):
        for p in vol["timeline"][0].get("data", []):
            vmap[p.get("date", "")[:10] if "-" in str(p.get("date")) else _norm(p.get("date"))] = p.get("value")

    out = []
    for p in tseries:
        d = _norm(p.get("date"))
        if not d or d > end:  # point-in-time guard
            continue
        out.append({"date": d, "tone": round(float(p.get("value", 0.0)), 3),
                    "volume": int(vmap.get(d, 0) or 0)})
    return out or None


def _norm(raw):
    """Normalise a GDELT date (e.g. '20260128T000000Z' or '2026-01-28...') to YYYY-MM-DD."""
    s = str(raw)
    if "-" in s:
        return s[:10]
    if len(s) >= 8 and s[:8].isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return ""


_avail = [None]


def available():
    """Cheap one-shot probe (cached per process). True if GDELT serves JSON."""
    if _avail[0] is None:
        r = _fetch({"query": "finance", "mode": "timelinetone",
                    "startdatetime": "20260101000000", "enddatetime": "20260102000000",
                    "format": "json"})
        _avail[0] = r is not None
    return _avail[0]


__all__ = ["tone_timeline", "available", "USER_AGENT"]
