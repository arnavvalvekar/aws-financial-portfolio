"""Tests for the deep-dive position rule (owner C, Phase 3).

    python -m unittest src.evidence.test_deepdive -v

The rule: deep-dive = the ticker with the largest analyst disagreement, read
from the run's disagreement.json (B's artifact). Tests use tiny synthetic run
dirs so they are offline and deterministic.
"""

import json
import tempfile
import unittest
from pathlib import Path

from . import deepdive


def _run_dir(tmp, disagreement=None, decision=None):
    d = Path(tmp)
    if disagreement is not None:
        (d / "disagreement.json").write_text(json.dumps(disagreement))
    if decision is not None:
        (d / "decision.json").write_text(json.dumps(decision))
    return d


class DeepDivePick(unittest.TestCase):
    def test_picks_highest_spread(self):
        dis = {
            "by_ticker": {
                "AAPL": {"spread": 0.1, "mean_stance": 0.3, "stances": {"technical": 0.3}},
                "MSFT": {"spread": 0.7, "mean_stance": 0.0, "stances": {"technical": -0.8, "fundamentals": 0.8}},
                "KO": {"spread": 0.2, "mean_stance": 0.1, "stances": {"macro": 0.1}},
            },
            "most_contested": ["MSFT", "KO", "AAPL"],
        }
        with tempfile.TemporaryDirectory() as tmp:
            pick = deepdive.pick(_run_dir(tmp, dis))
        self.assertEqual(pick["ticker"], "MSFT")
        self.assertEqual(pick["spread"], 0.7)
        self.assertIn("technical", pick["stances"])

    def test_uses_most_contested_order_for_ties(self):
        dis = {
            "by_ticker": {"A": {"spread": 0.5}, "B": {"spread": 0.5}},
            "most_contested": ["B", "A"],
        }
        with tempfile.TemporaryDirectory() as tmp:
            pick = deepdive.pick(_run_dir(tmp, dis))
        self.assertEqual(pick["ticker"], "B")  # ranking breaks the tie deterministically

    def test_attaches_decision_context(self):
        dis = {"by_ticker": {"MSFT": {"spread": 0.7}}, "most_contested": ["MSFT"]}
        dec = {
            "weights": {"MSFT": 0.1},
            "positions": {"MSFT": {"rationale": "moderate", "conflicts": ["tech vs fundamentals"],
                                    "sources": ["sec:MSFT:10-Q:2025-12-31:Revenues"],
                                    "change_triggers": ["close below 200d"]}},
        }
        with tempfile.TemporaryDirectory() as tmp:
            pick = deepdive.pick(_run_dir(tmp, dis, dec))
        self.assertEqual(pick["weight"], 0.1)
        self.assertEqual(pick["rationale"], "moderate")
        self.assertEqual(pick["conflicts"], ["tech vs fundamentals"])

    def test_none_when_no_disagreement_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(deepdive.pick(Path(tmp)))

    def test_none_when_empty_ranking(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(deepdive.pick(_run_dir(tmp, {"by_ticker": {}, "most_contested": []})))

    def test_write_creates_artifact(self):
        dis = {"by_ticker": {"MSFT": {"spread": 0.7}}, "most_contested": ["MSFT"]}
        with tempfile.TemporaryDirectory() as tmp:
            d = _run_dir(tmp, dis)
            out = deepdive.write(d)
            self.assertTrue((d / "deepdive.json").is_file())
            self.assertEqual(json.loads((d / "deepdive.json").read_text())["ticker"], "MSFT")
            self.assertEqual(out["ticker"], "MSFT")

    def test_rule_text_nonempty(self):
        self.assertIn("disagreement", deepdive.rule_text().lower())


if __name__ == "__main__":
    unittest.main()
