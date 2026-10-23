"""B's lane: validators, repair, consensus and the orchestrator, with a fake model (no AWS calls)."""

import json
import random

import pytest
import yaml

from src.agents import analysts, orchestrate, pm
from src.agents.consensus import disagreement
from src.agents.validate import (find_late_dates, repair_analyst, repair_weights,
                                 validate_analyst, validate_decision)

UNIVERSE = ["AAPL", "MSFT", "KO"]
ASOF = "2026-01-30"
CFG = {"universe": UNIVERSE, "asof": ASOF, "model": "fake", "region": "us-east-1",
       "constraints": {"max_weight": 0.5, "max_cash": 0.2}}
IDS = {f"px:{t}:{ASOF}" for t in UNIVERSE}


def pack(date=ASOF):
    return {"analyst": "technical", "asof": ASOF, "data_horizon": {"px": date},
            "items": [{"id": f"px:{t}:{ASOF}", "ticker": t, "date": date, "text": f"{t} text"} for t in UNIVERSE]}


def good_views(thesis="ok", evidence=None):
    return {"views": [{"ticker": t, "stance": 0.2, "confidence": 0.6, "thesis": thesis,
                       "evidence": evidence or [f"px:{t}:{ASOF}"], "change_triggers": ["x"]} for t in UNIVERSE]}


def good_decision(weights=None):
    weights = weights or {"AAPL": 0.4, "MSFT": 0.3, "KO": 0.2, "CASH": 0.1}
    return {"weights": weights, "portfolio_thesis": "t", "regime_view": "r",
            "positions": {t: {"rationale": "r", "analyst_weighting": {"technical": 1.0}, "conflicts": [],
                              "sources": [f"px:{t}:{ASOF}"], "confidence": 0.5, "change_triggers": ["x"]}
                          for t in UNIVERSE}}


# --- validators ---------------------------------------------------------------------------------
def test_find_late_dates_flags_only_dates_after_the_cutoff():
    assert find_late_dates({"a": "on 2026-01-30 and 2025-12-01"}, ASOF) == []
    assert find_late_dates({"a": "rallied on 2026-03-02"}, ASOF) == ["2026-03-02"]


def test_validate_analyst_flags_unknown_citation_missing_ticker_and_late_date():
    report = good_views(evidence=["px:AAPL:made-up"])
    report["views"].pop()  # drop KO
    report["views"][0]["thesis"] = "see 2026-02-14"
    errors = " | ".join(validate_analyst(report, UNIVERSE, IDS, ASOF))
    assert "not in the pack" in errors and "KO" in errors and "after the cutoff" in errors


def test_repair_analyst_drops_unknown_ids_and_clamps():
    report = good_views(evidence=["px:AAPL:made-up", f"px:AAPL:{ASOF}"])
    report["views"][0]["stance"] = 5
    fixed = repair_analyst(report, IDS)
    assert fixed["views"][0]["evidence"] == [f"px:AAPL:{ASOF}"] and fixed["views"][0]["stance"] == 1.0


def test_validate_decision_flags_cap_sum_and_invented_source():
    d = good_decision({"AAPL": 0.7, "MSFT": 0.3, "KO": 0.2, "CASH": 0.3})
    d["positions"]["AAPL"]["sources"] = ["px:AAPL:invented"]
    errors = " | ".join(validate_decision(d, UNIVERSE, 0.5, 0.2, IDS, ASOF))
    assert "above the cap" in errors and "sum" in errors and "not in any evidence pack" in errors


def test_repair_weights_always_sums_to_one_within_caps():
    rng = random.Random(3)
    names = UNIVERSE + ["CASH"]
    for _ in range(200):
        raw = {n: rng.uniform(-0.2, 1.5) for n in names if rng.random() > 0.2}
        w, _ = repair_weights(raw, UNIVERSE, 0.5, 0.2)
        assert abs(sum(w.values()) - 1) < 1e-6
        assert all(w[t] <= 0.5 + 1e-9 for t in UNIVERSE) and w["CASH"] <= 0.2 + 1e-9
        assert all(v >= 0 for v in w.values())


# --- consensus ----------------------------------------------------------------------------------
def test_disagreement_ranks_split_stocks_first_and_ignores_zero_confidence():
    def report(name, stances, conf=0.8):
        return {"analyst": name, "views": [{"ticker": t, "stance": s, "confidence": conf} for t, s in zip(UNIVERSE, stances)]}
    reports = [report("a", [0.9, 0.5, 0.0]), report("b", [-0.9, 0.5, 0.0]), report("c", [0.0, 0.5, 0.9], conf=0)]
    out = disagreement(reports)
    assert out["most_contested"][0] == "AAPL"
    assert out["by_ticker"]["MSFT"]["spread"] == 0
    assert out["by_ticker"]["KO"]["n_active"] == 2  # analyst c has no confidence


# --- orchestrator with a fake model -------------------------------------------------------------
@pytest.fixture
def fake_model(monkeypatch):
    state = {"analyst": good_views, "pm": good_decision, "calls": 0}

    def fake(*, tool_name, **_):
        state["calls"] += 1
        return state["pm"]() if tool_name == "submit_decision" else state["analyst"]()

    monkeypatch.setattr(analysts, "call_json", fake)
    monkeypatch.setattr(pm, "call_json", fake)
    return state


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(orchestrate, "ROOT", tmp_path)
    cfg = dict(CFG, universe=UNIVERSE, constraints=CFG["constraints"])
    (tmp_path / "config.yaml").write_text(yaml.safe_dump(cfg))
    ev = tmp_path / "evidence"
    ev.mkdir()
    (ev / "technical.json").write_text(json.dumps(pack()))
    return tmp_path


def test_end_to_end_writes_a_valid_decision(workspace, fake_model):
    out, decision, warnings = orchestrate.run(workspace / "config.yaml", workspace / "evidence", "t1")
    assert warnings == []
    assert abs(sum(decision["weights"].values()) - 1) < 1e-9
    assert (out / "decision.json").exists() and (out / "disagreement.json").exists()
    assert json.loads((out / "meta.json").read_text())["analysts"] == ["technical"]


def test_loader_refuses_evidence_dated_after_the_cutoff(workspace, fake_model):
    (workspace / "evidence" / "technical.json").write_text(json.dumps(pack(date="2026-03-02")))
    with pytest.raises(RuntimeError, match="after the cutoff"):
        orchestrate.run(workspace / "config.yaml", workspace / "evidence", "t2")
    assert fake_model["calls"] == 0  # refused before any model call


def test_a_future_date_in_model_output_stops_the_run(workspace, fake_model):
    fake_model["analyst"] = lambda: good_views(thesis="shares jumped on 2026-03-02")
    with pytest.raises(RuntimeError, match="look-ahead"):
        orchestrate.run(workspace / "config.yaml", workspace / "evidence", "t3")


def test_invented_citation_is_dropped_with_a_warning(workspace, fake_model):
    fake_model["analyst"] = lambda: good_views(evidence=["px:AAPL:invented"])
    out, decision, warnings = orchestrate.run(workspace / "config.yaml", workspace / "evidence", "t4")
    saved = json.loads((out / "analysts" / "technical.json").read_text())
    assert all(v["evidence"] == [] for v in saved["views"]) and warnings


def test_over_cap_weights_from_the_model_are_repaired(workspace, fake_model):
    fake_model["pm"] = lambda: good_decision({"AAPL": 0.9, "MSFT": 0.05, "KO": 0.05, "CASH": 0.0})
    out, decision, warnings = orchestrate.run(workspace / "config.yaml", workspace / "evidence", "t5")
    w = decision["weights"]
    assert abs(sum(w.values()) - 1) < 1e-6 and w["AAPL"] <= 0.5 + 1e-9 and warnings
