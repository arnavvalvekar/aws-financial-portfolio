"""Tests for CrashLab (owner C).

    python -m unittest src.crashlab.test_crashlab -v

Offline and deterministic: the default scenarios need no model and no network.
Covers the shock model, scenario specs, re-pricing math, worst-first ordering,
and protective proposals (constraint-respecting, grounded give-up).
"""

import unittest

from . import engine, protect, scenarios

CONFIG = {
    "universe": ["AAPL", "MSFT", "NVDA", "AMZN", "XOM", "JNJ", "PG", "CAT", "NEE", "KO"],
    "constraints": {"long_only": True, "max_weight": 0.25, "max_cash": 0.20},
    "costs_bps": 5,
}

DECISION = {
    "asof": "2026-01-30",
    "weights": {"AAPL": 0.14, "MSFT": 0.10, "NVDA": 0.12, "AMZN": 0.08, "XOM": 0.12,
                "JNJ": 0.10, "PG": 0.05, "CAT": 0.07, "NEE": 0.06, "KO": 0.10, "CASH": 0.06},
}


class ShockModel(unittest.TestCase):
    def test_cash_never_shocked(self):
        for s in scenarios.all_scenarios():
            self.assertEqual(engine.shock_return("CASH", s), 0.0)

    def test_sector_beta_applied(self):
        s = {"market_shock": -0.20, "sector_betas": {"tech": 1.5, "staples": 0.5}, "oil_shock": None}
        self.assertAlmostEqual(engine.shock_return("NVDA", s), -0.30)   # tech 1.5 * -0.20
        self.assertAlmostEqual(engine.shock_return("KO", s), -0.10)     # staples 0.5 * -0.20

    def test_defensive_sector_loses_less(self):
        s = {"market_shock": -0.30, "sector_betas": scenarios.DEFAULT_BETAS, "oil_shock": None}
        tech = engine.shock_return("AAPL", s)
        staple = engine.shock_return("KO", s)
        self.assertLess(tech, staple)  # tech more negative than staples

    def test_oil_overlay_helps_energy(self):
        # An oil spike (oil_shock negative in the 2020 sense is a crash; here test a benefit case)
        s = {"market_shock": -0.10, "sector_betas": {"energy": 1.0}, "oil_shock": -0.40}
        # energy return blends market (-0.10) with -oil_shock (+0.40): 0.5*-0.1 + 0.5*0.4 = +0.15
        self.assertAlmostEqual(engine.shock_return("XOM", s), 0.15)


class Scenarios(unittest.TestCase):
    def test_historical_have_sources_and_assumptions(self):
        for s in scenarios.HISTORICAL:
            self.assertTrue(s.get("source"), f"{s['id']} missing source")
            self.assertTrue(s.get("assumptions"))
            self.assertLess(s["market_shock"], 0)  # a crash is negative

    def test_invented_are_mechanism_grounded(self):
        for s in scenarios.INVENTED:
            self.assertTrue(s["mechanism"])
            self.assertIn("expected_casualties", s)
            self.assertIn("hypothetical", s["assumptions"].lower())

    def test_every_universe_name_has_a_sector(self):
        for t in CONFIG["universe"]:
            self.assertIn(t, scenarios.SECTOR)


class Repricing(unittest.TestCase):
    def test_stress_report_shape(self):
        r = engine.stress(DECISION, scenarios.HISTORICAL[0], CONFIG)
        for k in ("scenario", "label", "kind", "portfolio_shock", "culprits", "mechanism"):
            self.assertIn(k, r)
        self.assertLess(r["portfolio_shock"], 0)  # a crash loses money

    def test_cost_drag_included(self):
        r = engine.stress(DECISION, scenarios.HISTORICAL[0], CONFIG)
        self.assertLess(r["cost_drag"], 0)  # one-time cost is a drag

    def test_worst_first_ordering(self):
        reports = engine.run(DECISION, CONFIG, scenarios.all_scenarios())
        shocks = [r["portfolio_shock"] for r in reports]
        self.assertEqual(shocks, sorted(shocks))  # most negative first

    def test_gfc_worse_than_covid(self):
        reports = {r["scenario"]: r["portfolio_shock"] for r in
                   engine.run(DECISION, CONFIG, scenarios.HISTORICAL)}
        self.assertLess(reports["gfc_2008"], reports["covid_2020"])

    def test_culprits_are_worst_contributors(self):
        r = engine.stress(DECISION, scenarios.INVENTED[2], CONFIG)  # tech selloff
        top = r["culprits"][0]["ticker"]
        self.assertIn(top, {"AAPL", "NVDA", "MSFT"})  # a tech name does the most damage


class Protect(unittest.TestCase):
    def _metrics(self):
        # base-case contributions: weight * window-return; pick simple positive returns
        contrib = {t: w * 0.10 for t, w in DECISION["weights"].items() if t != "CASH"}
        contrib["CASH"] = 0.0
        return {"contributions": contrib}

    def test_proposals_respect_cash_cap(self):
        worst = scenarios.HISTORICAL[0]
        out = protect.propose(DECISION, worst, CONFIG, self._metrics())
        for p in out["proposals"]:
            # trimming into cash must not exceed the cash cap
            self.assertLessEqual(DECISION["weights"]["CASH"] + p["trim"], 0.20 + 1e-9)

    def test_proposals_reduce_shock(self):
        worst = scenarios.HISTORICAL[0]
        out = protect.propose(DECISION, worst, CONFIG, self._metrics())
        self.assertTrue(out["proposals"])
        for p in out["proposals"]:
            self.assertGreater(p["shock_drawdown_removed"], 0)  # less bad after trim

    def test_give_up_grounded_in_metrics(self):
        worst = scenarios.HISTORICAL[0]
        out = protect.propose(DECISION, worst, CONFIG, self._metrics())
        # base return is 0.10 for every name in the synthetic metrics
        for p in out["proposals"]:
            self.assertAlmostEqual(p["base_case_return_given_up"], p["trim"] * 0.10, places=6)

    def test_decision_not_mutated(self):
        before = dict(DECISION["weights"])
        protect.propose(DECISION, scenarios.HISTORICAL[0], CONFIG, self._metrics())
        self.assertEqual(DECISION["weights"], before)  # proposals never touch the frozen weights


if __name__ == "__main__":
    unittest.main()
