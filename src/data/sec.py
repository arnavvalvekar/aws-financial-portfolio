"""SEC data access for the fundamentals pipeline (owner C).

The only entry points are:
  - ticker_to_cik(ticker)   map a ticker to its zero-padded 10-digit CIK
  - company_facts(ticker)   the full XBRL companyfacts blob, cached to data/raw/

Point-in-time discipline lives in the evidence layer, not here: this module
only fetches. The gate on the `filed` date happens in evidence/fundamentals.py.

SEC asks for a descriptive User-Agent with contact info and rate-limits to
about 10 requests a second. We cache raw downloads under data/raw/ (git-ignored)
so a re-run makes no network calls.
"""

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "sec"

# SEC requires a User-Agent that identifies the caller. Override via the
# SEC_USER_AGENT env var with your own contact string for a real run.
import os

USER_AGENT = os.environ.get(
    "SEC_USER_AGENT", "aws-financial-portfolio hackathon research contact@example.com"
)

_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
_CONCEPT_URL = "https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/{tag}.json"

# Pinned CIKs for the universe. The public SEC ticker->CIK table is mutable and
# occasionally points a ticker at a brand-new shell entity rather than the
# operating company with the filing history. As of Oct 2026 "XOM" resolves to
# "ExxonMobil Holdings Corp" (CIK 2115436, almost no filings) instead of the
# historical "Exxon Mobil Corporation" (CIK 34088). Pinning keeps the mapping
# correct and auditable; a reviewer can see exactly which filer each ticker used.
CIK_OVERRIDES = {
    "XOM": 34088,  # Exxon Mobil Corporation (not the newer holdings shell)
}

_last_call = [0.0]
_MIN_INTERVAL = 0.15  # seconds between requests, under SEC's ~10/s limit


def _get(url, dest):
    """Fetch url to dest (a Path), with a polite rate limit. Returns the bytes."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    wait = _MIN_INTERVAL - (time.time() - _last_call[0])
    if wait > 0:
        time.sleep(wait)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read()
    _last_call[0] = time.time()
    dest.write_bytes(body)
    return body


def _ticker_map():
    """The SEC ticker->CIK table, cached. Keys are upper-case tickers."""
    cache = RAW / "company_tickers.json"
    if cache.exists():
        raw = cache.read_bytes()
    else:
        raw = _get(_TICKERS_URL, cache)
    table = json.loads(raw)
    out = {}
    for row in table.values():
        out[row["ticker"].upper()] = int(row["cik_str"])
    return out


def ticker_to_cik(ticker):
    """Return the zero-padded 10-digit CIK string for a ticker, e.g. '0000320193'.

    Honours CIK_OVERRIDES first so the universe pins to the intended filer.
    """
    t = ticker.upper()
    if t in CIK_OVERRIDES:
        return f"{CIK_OVERRIDES[t]:010d}"
    m = _ticker_map()
    if t not in m:
        raise KeyError(f"ticker {ticker!r} not found in SEC company_tickers table")
    return f"{m[t]:010d}"


def company_facts(ticker, refresh=False):
    """Return the parsed XBRL companyfacts dict for a ticker, cached under data/raw/sec/."""
    cik = ticker_to_cik(ticker)
    cache = RAW / f"companyfacts_CIK{cik}.json"
    if cache.exists() and not refresh:
        return json.loads(cache.read_bytes())
    raw = _get(_FACTS_URL.format(cik=cik), cache)
    return json.loads(raw)


def company_concept(ticker, tag, refresh=False):
    """Return the USD unit entries for one us-gaap concept/tag, cached.

    The per-concept endpoint is more complete than the companyfacts aggregate
    for some large filers (e.g. XOM), whose aggregate blob can be thin or stale.
    Returns a list of fact dicts (possibly empty); never raises on a missing tag.
    """
    cik = ticker_to_cik(ticker)
    cache = RAW / f"concept_CIK{cik}_{tag}.json"
    if cache.exists() and not refresh:
        raw = cache.read_bytes()
    else:
        try:
            raw = _get(_CONCEPT_URL.format(cik=cik, tag=tag), cache)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:  # company never reported this tag
                cache.write_bytes(b'{"units": {}}')
                return []
            raise
    data = json.loads(raw)
    return data.get("units", {}).get("USD", [])


def map_universe(universe):
    """Return {ticker: cik} for a list of tickers. Handy for a quick go/no-go check."""
    return {t: ticker_to_cik(t) for t in universe}


__all__ = ["ticker_to_cik", "company_facts", "company_concept", "map_universe", "USER_AGENT"]
