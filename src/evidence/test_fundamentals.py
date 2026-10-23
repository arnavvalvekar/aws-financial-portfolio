"""Tests for the fundamentals evidence pipeline (owner C).

Run with the stdlib test runner (no extra dependency):

    python -m unittest src.evidence.test_fundamentals -v

Covers the three areas the brief asks for:
  - data extraction      (facts_table picks the right fact per metric)
  - evidence formatting   (pack/CSV shape, evidence-ID format, schema fields)
  - cutoff-date enforcement (nothing dated after asof; gate on the filed date)

The logic tests use small synthetic companyfacts blobs injected via
unittest.mock, so they run offline and deterministically. One integration
smoke test runs against the real cached SEC data when it is present, and
skips cleanly when it is not (e.g. a fresh CI checkout with no cache).
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from . import fundamentals as F

ROOT = Path(__file__).resolve().parents[2]


def _facts(gaap_tags):
    """Wrap a {tag: [entries]} dict into the companyfacts structure."""
    return {"facts": {"us-gaap": {t: {"units": {"USD": e}} for t, e in gaap_tags.items()}}}


def _q(end, filed, val, start=None, form="10-Q"):
    """One quarterly flow entry (start..end ~ 91 days, inside the code's 80-100 window)."""
    import datetime

    if start is None:
        e = datetime.date.fromisoformat(end)
        start = (e - datetime.timedelta(days=91)).isoformat()
    return {"start": start, "end": end, "val": val, "form": form, "filed": filed}


def _inst(end, filed, val, form="10-Q"):
    """One balance-sheet (instant) entry."""
    return {"end": end, "val": val, "form": form, "filed": filed}


class CutoffEnforcement(unittest.TestCase):
    """The point-in-time guard: gate on filed date, never leak a later filing."""

    def _patch(self, facts):
        p1 = mock.patch.object(F, "company_facts", return_value=facts)
        p2 = mock.patch.object(F, "company_concept", return_value=[])
        p1.start(); p2.start()
        self.addCleanup(p1.stop); self.addCleanup(p2.stop)

    def test_filing_after_cutoff_is_excluded(self):
        # Two revenue facts: one filed before the cutoff, one after. Only the
        # earlier filing may be used, even though the later one has a newer period.
        facts = _facts({"Revenues": [
            _q("2025-09-30", filed="2025-10-25", val=100),
            _q("2025-12-31", filed="2026-02-10", val=130),  # filed AFTER asof
        ]})
        self._patch(facts)
        table = F.facts_table("TEST", "2026-01-30")
        self.assertIn("Revenues", table)
        self.assertEqual(table["Revenues"]["period_end"], "2025-09-30")
        self.assertEqual(table["Revenues"]["filed"], "2025-10-25")

    def test_gate_is_filed_date_not_period_end(self):
        # A filing covering an old period but filed before the cutoff IS allowed;
        # a filing covering a recent period but filed after the cutoff is NOT.
        facts = _facts({"Revenues": [
            _q("2024-12-31", filed="2025-02-01", val=90),   # old period, early filing: allowed
            _q("2025-12-31", filed="2026-03-01", val=150),  # recent period, late filing: blocked
        ]})
        self._patch(facts)
        table = F.facts_table("TEST", "2026-01-30")
        self.assertEqual(table["Revenues"]["period_end"], "2024-12-31")

    def test_pack_has_no_date_after_cutoff(self):
        facts = _facts({
            "Revenues": [_q("2025-09-30", "2025-10-25", 100), _q("2024-09-30", "2024-10-25", 80)],
            "Assets": [_inst("2025-09-30", "2025-10-25", 1000)],
            "StockholdersEquity": [_inst("2025-09-30", "2025-10-25", 400)],
            "NetIncomeLoss": [_q("2025-09-30", "2025-10-25", 20)],
        })
        self._patch(facts)
        pack = F.build_pack(["TEST"], "2026-01-30")
        for item in pack["items"]:
            self.assertLessEqual(item["date"], "2026-01-30")
        # data_horizon never exceeds the cutoff
        self.assertLessEqual(pack["data_horizon"]["sec"], "2026-01-30")

    def test_cutoff_moves_the_horizon(self):
        facts = _facts({"Revenues": [
            _q("2025-03-31", "2025-05-01", 100),
            _q("2025-09-30", "2025-11-01", 110),
        ]})
        self._patch(facts)
        early = F.facts_table("TEST", "2025-06-30")
        late = F.facts_table("TEST", "2026-01-30")
        self.assertEqual(early["Revenues"]["period_end"], "2025-03-31")
        self.assertEqual(late["Revenues"]["period_end"], "2025-09-30")


class DataExtraction(unittest.TestCase):
    """Tag selection: candidate fallback, most-recent wins, staleness, missing data."""

    def _patch(self, facts, concept=None):
        p1 = mock.patch.object(F, "company_facts", return_value=facts)
        p2 = mock.patch.object(F, "company_concept",
                               side_effect=(lambda t, tag: (concept or {}).get(tag, [])))
        p1.start(); p2.start()
        self.addCleanup(p1.stop); self.addCleanup(p2.stop)

    def test_candidate_tag_fallback(self):
        # Preferred Revenue tag absent; the secondary 'Revenues' tag is used.
        facts = _facts({"Revenues": [_q("2025-09-30", "2025-10-25", 100)]})
        self._patch(facts)
        table = F.facts_table("TEST", "2026-01-30")
        self.assertEqual(table["Revenues"]["tag"], "Revenues")

    def test_most_recent_tag_wins_on_migration(self):
        # Company migrated from an old tag (stale period) to a new one (fresh period).
        # The fresher period must win even though the old tag is listed first.
        facts = _facts({
            "RevenueFromContractWithCustomerExcludingAssessedTax": [_q("2023-06-30", "2023-08-01", 80)],
            "Revenues": [_q("2025-09-30", "2025-11-03", 120)],
        })
        self._patch(facts)
        table = F.facts_table("TEST", "2026-01-30")
        self.assertEqual(table["Revenues"]["period_end"], "2025-09-30")
        self.assertEqual(table["Revenues"]["tag"], "Revenues")

    def test_stale_abandoned_tag_dropped(self):
        # A tag whose latest value is years before the cutoff is dropped rather
        # than presented as current (mirrors XOM's abandoned LongTermDebt tag).
        facts = _facts({
            "Revenues": [_q("2025-09-30", "2025-11-03", 120)],
            "LongTermDebtNoncurrent": [_inst("2017-12-31", "2018-02-20", 23)],
        })
        self._patch(facts)
        table = F.facts_table("TEST", "2026-01-30")
        self.assertIn("Revenues", table)
        self.assertNotIn("LongTermDebt", table)  # too stale

    def test_missing_metric_is_omitted_not_fabricated(self):
        facts = _facts({"Revenues": [_q("2025-09-30", "2025-11-03", 120)]})
        self._patch(facts)
        table = F.facts_table("TEST", "2026-01-30")
        # No equity/assets data supplied -> those metrics simply absent.
        self.assertNotIn("StockholdersEquity", table)
        self.assertNotIn("Assets", table)

    def test_concept_fallback_used_when_facts_thin(self):
        # companyfacts has only a post-cutoff entry; the concept endpoint carries
        # the usable pre-cutoff history. The fallback should be consulted.
        facts = _facts({"Revenues": [_q("2026-06-30", "2026-08-03", 200)]})
        concept = {"Revenues": [_q("2025-09-30", "2025-11-03", 120)]}
        self._patch(facts, concept)
        table = F.facts_table("TEST", "2026-01-30")
        self.assertEqual(table["Revenues"]["period_end"], "2025-09-30")

    def test_missing_ticker_recorded(self):
        self._patch(_facts({}))  # no usable facts at all
        pack = F.build_pack(["TEST"], "2026-01-30")
        self.assertEqual(pack["items"], [])
        self.assertIn("TEST", pack.get("missing_tickers", []))


class EvidenceFormatting(unittest.TestCase):
    """Evidence-ID format, pack schema, derived reads, and CSV shape."""

    def setUp(self):
        facts = _facts({
            "Revenues": [_q("2025-09-30", "2025-11-03", 1000), _q("2024-09-30", "2024-11-03", 800)],
            "OperatingIncomeLoss": [_q("2025-09-30", "2025-11-03", 200)],
            "NetIncomeLoss": [_q("2025-09-30", "2025-11-03", 150)],
            "Assets": [_inst("2025-09-30", "2025-11-03", 5000)],
            "Liabilities": [_inst("2025-09-30", "2025-11-03", 3000)],
            "StockholdersEquity": [_inst("2025-09-30", "2025-11-03", 2000)],
        })
        p1 = mock.patch.object(F, "company_facts", return_value=facts)
        p2 = mock.patch.object(F, "company_concept", return_value=[])
        p1.start(); p2.start()
        self.addCleanup(p1.stop); self.addCleanup(p2.stop)
        self.pack = F.build_pack(["TEST"], "2026-01-30")

    def test_evidence_id_format(self):
        # sec:<TICKER>:<form>:<period-end>:<tag>  (SCHEMAS.md)
        ids = [i["id"] for i in self.pack["items"]]
        self.assertTrue(ids, "expected at least one evidence item")
        for eid in ids:
            parts = eid.split(":")
            self.assertEqual(parts[0], "sec")
            self.assertEqual(parts[1], "TEST")
            self.assertEqual(len(parts), 5, f"malformed id: {eid}")

    def test_pack_schema_fields(self):
        self.assertEqual(self.pack["analyst"], "fundamentals")
        self.assertEqual(self.pack["asof"], "2026-01-30")
        self.assertIn("sec", self.pack["data_horizon"])
        for item in self.pack["items"]:
            self.assertEqual(set(item), {"id", "ticker", "date", "text"})

    def test_items_json_serialisable(self):
        # The orchestrator serialises the pack; make sure it round-trips.
        s = json.dumps(self.pack)
        self.assertEqual(json.loads(s)["analyst"], "fundamentals")

    def test_yoy_growth_computed(self):
        # Revenue 1000 vs prior-year 800 -> +25%.
        rev = [i for i in self.pack["items"]
               if i["id"].endswith(":Revenues") or ":Revenues" in i["id"]]
        texts = " ".join(i["text"] for i in self.pack["items"])
        self.assertIn("Year on year +25.0%", texts)

    def test_derived_margins_present(self):
        texts = " ".join(i["text"] for i in self.pack["items"])
        self.assertIn("Operating margin 20.0%", texts)  # 200/1000
        self.assertIn("Net margin 15.0%", texts)        # 150/1000
        self.assertIn("Leverage: total liabilities / equity 1.50x", texts)  # 3000/2000
        self.assertIn("Return on equity 7.5%", texts)   # 150/2000

    def test_csv_written_with_filing_dates(self):
        with tempfile.TemporaryDirectory() as d:
            csv_path = Path(d) / "f.csv"
            n = F.write_csv(csv_path, ["TEST"], "2026-01-30")
            text = csv_path.read_text()
            header = text.splitlines()[0]
            self.assertEqual(
                header,
                "ticker,metric,tag,value,period_end,form,filed,yoy,evidence_id",
            )
            self.assertGreater(n, 0)
            self.assertIn("2025-11-03", text)  # a filing date appears

    def test_write_pack_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "fundamentals.json"
            F.write_pack(out, ["TEST"], "2026-01-30")
            loaded = json.loads(out.read_text())
            self.assertEqual(loaded["analyst"], "fundamentals")


class IntegrationSmoke(unittest.TestCase):
    """Runs against the real cached SEC data if present; skips otherwise."""

    def test_real_universe_pack_if_cached(self):
        import yaml

        cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
        universe, asof = cfg["universe"], str(cfg["asof"])
        raw = ROOT / "data" / "raw" / "sec"
        if not raw.exists() or not any(raw.glob("companyfacts_*.json")):
            self.skipTest("no cached SEC data (run the pipeline once to populate data/raw/)")
        pack = F.build_pack(universe, asof)
        covered = {i["ticker"] for i in pack["items"]}
        self.assertEqual(covered, set(universe), f"missing: {set(universe) - covered}")
        for item in pack["items"]:
            self.assertLessEqual(item["date"], asof)  # no look-ahead


if __name__ == "__main__":
    unittest.main()
