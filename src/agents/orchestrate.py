"""Run the analysts in parallel, then the portfolio manager, and save every input and output."""

import json
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

from .analysts import run_analyst
from .consensus import disagreement
from .pm import run_pm
from .schemas import ANALYSTS

ROOT = Path(__file__).resolve().parents[2]


def load_config(path):
    return yaml.safe_load(Path(path).read_text())


def load_evidence(evidence_dir, asof, only=None):
    """Read evidence/<analyst>.json for each analyst that has a file. Refuses any item dated after the cutoff."""
    packs = {}
    for name in only or ANALYSTS:
        f = Path(evidence_dir) / f"{name}.json"
        if not f.exists():
            continue
        pack = json.loads(f.read_text())
        late = [i["id"] for i in pack["items"] if str(i["date"]) > asof]
        if late:
            raise RuntimeError(f"{name}: evidence dated after the cutoff {asof}: {late[:5]}")
        packs[name] = pack
    return packs


def run(config_path, evidence_dir, run_id=None, only=None, use_cache=True):
    cfg = load_config(config_path)
    asof = str(cfg["asof"])
    packs = load_evidence(evidence_dir, asof, only)
    if not packs:
        raise RuntimeError(f"no evidence files found in {evidence_dir}")

    run_id = run_id or time.strftime("%Y%m%d-%H%M%S")
    out = ROOT / "runs" / run_id
    (out / "evidence").mkdir(parents=True, exist_ok=True)
    (out / "analysts").mkdir(exist_ok=True)
    for name in packs:
        shutil.copy(Path(evidence_dir) / f"{name}.json", out / "evidence" / f"{name}.json")

    with ThreadPoolExecutor(max_workers=len(packs)) as pool:
        futures = {n: pool.submit(run_analyst, n, p, cfg, use_cache) for n, p in packs.items()}
        results = {n: f.result() for n, f in futures.items()}
    reports, warnings = [], []
    for name, (report, warn) in results.items():
        (out / "analysts" / f"{name}.json").write_text(json.dumps(report, indent=2))
        reports.append(report)
        warnings += warn

    known_ids = {i["id"] for p in packs.values() for i in p["items"]}
    agreement = disagreement(reports)
    (out / "disagreement.json").write_text(json.dumps(agreement, indent=2))
    decision, warn = run_pm(reports, known_ids, cfg, use_cache, agreement)
    warnings += warn
    (out / "decision.json").write_text(json.dumps(decision, indent=2))
    (out / "meta.json").write_text(json.dumps(
        {"run_id": run_id, "asof": asof, "model": cfg["model"], "region": cfg.get("region", "us-east-1"),
         "analysts": list(packs), "warnings": warnings,
         "fixture": any(p.get("fixture") for p in packs.values())}, indent=2))
    return out, decision, warnings
