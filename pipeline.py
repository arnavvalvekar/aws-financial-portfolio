"""One command for the whole chain: build technical evidence, run the agents, score the decision.

    python pipeline.py [--run-id final] [--no-cache]

Fundamentals (and any other pack) is read from evidence/. The technical and macro packs are rebuilt
from the committed price store, so nothing here needs the network except the model calls.
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from src.agents.orchestrate import load_config, run
from src.evidence.macro import build_macro_evidence
from src.evidence.regime import build_regime_evidence
from src.evidence.technical import build_technical_evidence

ROOT = Path(__file__).resolve().parent


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--config", default="config.yaml")
    p.add_argument("--evidence", default="evidence", help="folder with <analyst>.json packs")
    p.add_argument("--run-id", default="dev-" + time.strftime("%Y%m%d-%H%M%S"))
    p.add_argument("--only", nargs="*", help="run only these analysts")
    p.add_argument("--no-cache", action="store_true")
    a = p.parse_args()
    config = ROOT / a.config
    evidence = ROOT / a.evidence

    cfg = load_config(config)
    pack = build_technical_evidence(str(cfg["asof"]), cfg["universe"], str(ROOT / "data" / "prices"))
    evidence.mkdir(exist_ok=True)
    (evidence / "technical.json").write_text(json.dumps(pack, indent=1))
    macro = build_macro_evidence(str(cfg["asof"]), str(ROOT / "data" / "prices"))
    regime = build_regime_evidence(str(cfg["asof"]), cfg["universe"], str(ROOT / "data" / "prices"))
    macro["items"] += [i for i in regime["items"] if i["ticker"] == "SPY"]  # market-wide crash-risk item
    (evidence / "macro.json").write_text(json.dumps(macro, indent=1))
    (evidence / "regime.json").write_text(json.dumps(regime, indent=1))  # read by the risk review only
    print(f"[1/3] evidence: technical {len(pack['items'])} items, macro {len(macro['items'])} items, "
          f"data horizon {pack['data_horizon']}")

    out, decision, warnings = run(config, evidence, a.run_id, a.only, not a.no_cache)
    print(f"[2/3] agents done, saved to {out}")
    for t, w in sorted(decision["weights"].items(), key=lambda kv: -kv[1]):
        print(f"      {t:<6} {w:6.1%}")
    for w in warnings:
        print("      warning:", w)
    review = out / "risk_review.json"
    if review.exists():
        r = json.loads(review.read_text())
        print(f"      risk review ({r['mode']}): {r['verdict']}, failed checks: {r['failed_checks'] or 'none'}")
        for reason in r["reasons"][:4]:
            print("        -", reason)

    print("[3/3] backtest")
    subprocess.run([sys.executable, "-m", "src.backtest", "--config", str(config),
                    "--decision", str(out / "decision.json"), "--run-id", a.run_id,
                    "--store-dir", str(ROOT / "data" / "prices")], cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
