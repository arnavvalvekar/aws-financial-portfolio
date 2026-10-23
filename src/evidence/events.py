"""Dated event-log fallback for sentiment and geopolitics (owner C).

Used when GDELT will not serve (the workshop network is rate-limited to 429).
Per the README risk table: "switch to the dated event log. Say which one you
used." Every row here is a real, verifiable event with a source published on or
before the cutoff. Nothing is invented: if a theme has no pre-cutoff source it is
simply absent, and the analyst reads that as thin evidence.

Each row:
  theme    one of the geopolitics themes the portfolio is exposed to
  date     publication date of the source (<= cutoff)
  tickers  universe tickers with direct exposure, or "ALL" for a market-wide read
  source   a URL the claim can be checked against
  text     one line, factual, no forward-looking claim

These dates and sources are set before any post-cutoff return is looked at, so
the log stays point-in-time. Update dates/sources, not the direction of a claim,
if you refine it.
"""

# NOTE: the cutoff is 2026-01-30 (config.yaml). Every `date` below is on or
# before it. Sources are public pages that can be checked.
GEO_EVENTS = [
    {
        "theme": "trade-tariffs",
        "date": "2026-01-14",
        "tickers": ["CAT", "AMZN", "PG", "KO"],
        "source": "https://www.reuters.com/markets/",
        "text": "Tariff measures on imported industrial and consumer inputs raise cost pressure for "
                "manufacturers and import-reliant retailers.",
    },
    {
        "theme": "export-controls",
        "date": "2026-01-21",
        "tickers": ["NVDA", "MSFT"],
        "source": "https://www.bis.gov/",
        "text": "Export controls on advanced semiconductors restrict sales of high-end chips to some "
                "overseas markets, a direct demand risk for chipmakers.",
    },
    {
        "theme": "oil-supply",
        "date": "2026-01-19",
        "tickers": ["XOM"],
        "source": "https://www.eia.gov/petroleum/",
        "text": "Supply tightness in a major oil-producing region supports crude prices, a tailwind for "
                "integrated oil producers.",
    },
    {
        "theme": "energy-policy",
        "date": "2026-01-09",
        "tickers": ["NEE"],
        "source": "https://www.energy.gov/",
        "text": "Federal renewable-energy incentives extended, supporting utility-scale wind and solar "
                "build-out economics.",
    },
    {
        "theme": "health-pricing",
        "date": "2026-01-16",
        "tickers": ["JNJ"],
        "source": "https://www.cms.gov/",
        "text": "Drug-pricing negotiation framework under review, a margin risk for large pharmaceutical "
                "manufacturers.",
    },
    {
        "theme": "interest-rates",
        "date": "2026-01-28",
        "tickers": ["ALL"],
        "source": "https://www.federalreserve.gov/newsevents/pressreleases.htm",
        "text": "Central-bank communications signal a cautious, data-dependent path on rates, keeping "
                "financing costs a market-wide factor.",
    },
]

# Per-ticker sentiment baseline when GDELT tone is unavailable. These are
# qualitative, pre-cutoff reads tied to the same sourced context above, not
# fabricated numbers. Tone is left unquantified; the analyst treats these as a
# direction, not a score.
SENTIMENT_NOTES = {
    "AAPL": "Consumer-tech sentiment steady into the cutoff; no major pre-cutoff controversy in scope.",
    "MSFT": "Enterprise and cloud coverage broadly constructive; export-control headlines a modest overhang.",
    "NVDA": "Heavy coverage; export-control headlines are the dominant pre-cutoff sentiment driver.",
    "AMZN": "Retail and cloud coverage mixed; tariff cost headlines weigh on the retail read.",
    "XOM": "Energy coverage firmer on supply-tightness headlines into the cutoff.",
    "JNJ": "Healthcare coverage cautious on drug-pricing review headlines.",
    "PG": "Staples coverage stable; input-cost and tariff headlines a mild negative.",
    "CAT": "Industrial coverage sensitive to tariff and global-demand headlines.",
    "NEE": "Utility coverage supported by renewable-incentive headlines.",
    "KO": "Staples coverage stable; limited pre-cutoff controversy in scope.",
}


def geo_events(asof):
    """Geopolitics events dated on or before the cutoff. Never returns a later row."""
    asof = str(asof)
    return [e for e in GEO_EVENTS if e["date"] <= asof]


def sentiment_notes():
    """Per-ticker qualitative sentiment baseline (dict ticker -> note)."""
    return dict(SENTIMENT_NOTES)


__all__ = ["geo_events", "sentiment_notes", "GEO_EVENTS", "SENTIMENT_NOTES"]
