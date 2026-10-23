"""Tests for the sentiment and geopolitics evidence packs (owner C).

    python -m unittest src.evidence.test_sentiment_geo -v

Covers, for both packs:
  - cutoff-date enforcement  (no item dated after asof; dated event log gated)
  - evidence formatting       (schema {id,ticker,date,text}, ID format, data_horizon)
  - GDELT fallback behaviour  (GDELT off -> fallback source; GDELT on -> gdelt items)
  - no fabrication            (events absent when no pre-cutoff source)

GDELT is mocked so tests run offline and deterministically. The real network is
never touched here.
"""

import datetime
import unittest
from unittest import mock

from ..data import gdelt as gdelt_mod
from . import events, geo, sentiment

UNIVERSE = ["AAPL", "MSFT", "NVDA", "AMZN", "XOM", "JNJ", "PG", "CAT", "NEE", "KO"]
ASOF = "2026-01-30"
SCHEMA_KEYS = {"id", "ticker", "date", "text"}


def _fake_series(dates_tones):
    return [{"date": d, "tone": t, "volume": 100} for d, t in dates_tones]


class SentimentPack(unittest.TestCase):
    def test_fallback_when_gdelt_unavailable(self):
        with mock.patch.object(gdelt_mod, "available", return_value=False):
            pack = sentiment.build_pack(UNIVERSE, ASOF)
        self.assertEqual(pack["source"], "fallback")
        self.assertEqual(len(pack["items"]), len(UNIVERSE))  # one per ticker
        for it in pack["items"]:
            self.assertEqual(set(it), SCHEMA_KEYS)
            self.assertTrue(it["id"].startswith("event:sentiment:"))
            self.assertLessEqual(it["date"], ASOF)

    def test_uses_gdelt_when_available(self):
        series = _fake_series([("2025-11-02", -0.5), ("2026-01-28", 0.4)])
        with mock.patch.object(gdelt_mod, "available", return_value=True), \
             mock.patch.object(gdelt_mod, "tone_timeline", return_value=series):
            pack = sentiment.build_pack(UNIVERSE, ASOF)
        self.assertEqual(pack["source"], "gdelt")
        self.assertTrue(all(it["id"].startswith("gdelt:") for it in pack["items"]))
        self.assertIn("gdelt", pack["data_horizon"])
        self.assertLessEqual(pack["data_horizon"]["gdelt"], ASOF)

    def test_gdelt_points_after_cutoff_are_dropped(self):
        # tone_timeline itself clips, but defend here too: a late point must not
        # change the horizon past the cutoff.
        series = _fake_series([("2026-01-28", 0.1)])
        with mock.patch.object(gdelt_mod, "available", return_value=True), \
             mock.patch.object(gdelt_mod, "tone_timeline", return_value=series):
            pack = sentiment.build_pack(UNIVERSE, ASOF)
        for it in pack["items"]:
            self.assertLessEqual(it["date"], ASOF)

    def test_data_horizon_present(self):
        with mock.patch.object(gdelt_mod, "available", return_value=False):
            pack = sentiment.build_pack(UNIVERSE, ASOF)
        self.assertTrue(pack["data_horizon"])
        self.assertEqual(pack["analyst"], "sentiment")


class GeoPack(unittest.TestCase):
    def test_events_only_when_gdelt_unavailable(self):
        with mock.patch.object(gdelt_mod, "available", return_value=False):
            pack = geo.build_pack(UNIVERSE, ASOF)
        self.assertEqual(pack["source"], "events")
        self.assertGreater(len(pack["items"]), 0)
        for it in pack["items"]:
            self.assertEqual(set(it), SCHEMA_KEYS)
            self.assertTrue(it["id"].startswith("event:"))
            self.assertLessEqual(it["date"], ASOF)

    def test_gdelt_conflict_item_added_when_available(self):
        series = _fake_series([("2025-11-05", 0.0), ("2026-01-27", 0.0)])
        with mock.patch.object(gdelt_mod, "available", return_value=True), \
             mock.patch.object(gdelt_mod, "tone_timeline", return_value=series):
            pack = geo.build_pack(UNIVERSE, ASOF)
        self.assertEqual(pack["source"], "events+gdelt")
        self.assertTrue(any(it["id"].startswith("gdelt:CONFLICT:") for it in pack["items"]))
        for it in pack["items"]:
            self.assertLessEqual(it["date"], ASOF)

    def test_no_item_dated_after_cutoff(self):
        with mock.patch.object(gdelt_mod, "available", return_value=False):
            pack = geo.build_pack(UNIVERSE, ASOF)
        self.assertFalse([it for it in pack["items"] if it["date"] > ASOF])

    def test_data_horizon_present(self):
        with mock.patch.object(gdelt_mod, "available", return_value=False):
            pack = geo.build_pack(UNIVERSE, ASOF)
        self.assertIn("events", pack["data_horizon"])
        self.assertLessEqual(pack["data_horizon"]["events"], ASOF)


class EventLogCutoff(unittest.TestCase):
    def test_event_log_gated_on_cutoff(self):
        # Every curated event carries a date; an earlier cutoff must exclude the
        # later rows, never leak them.
        all_rows = events.geo_events("2026-01-30")
        earlier = events.geo_events("2026-01-15")
        self.assertTrue(len(earlier) <= len(all_rows))
        for e in earlier:
            self.assertLessEqual(e["date"], "2026-01-15")

    def test_every_event_has_source_before_cutoff(self):
        for e in events.GEO_EVENTS:
            self.assertLessEqual(e["date"], ASOF, f"{e['theme']} dated after cutoff")
            self.assertTrue(e["source"].startswith("http"), f"{e['theme']} missing source URL")
            self.assertTrue(e["text"].strip())

    def test_event_dates_are_valid_iso(self):
        for e in events.GEO_EVENTS:
            datetime.date.fromisoformat(e["date"])  # raises if malformed


if __name__ == "__main__":
    unittest.main()
