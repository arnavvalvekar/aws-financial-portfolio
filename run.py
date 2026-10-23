"""Run the agent pipeline: python run.py --config config.yaml --evidence <dir> [--run-id id]."""

import argparse

from src.agents.orchestrate import run


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--config", default="config.yaml")
    p.add_argument("--evidence", default="fixtures/evidence", help="folder with <analyst>.json packs")
    p.add_argument("--run-id")
    p.add_argument("--only", nargs="*", help="run only these analysts")
    p.add_argument("--no-cache", action="store_true")
    a = p.parse_args()
    out, decision, warnings = run(a.config, a.evidence, a.run_id, a.only, not a.no_cache)
    print(f"run saved to {out}")
    for t, w in sorted(decision["weights"].items(), key=lambda kv: -kv[1]):
        print(f"  {t:<6} {w:6.1%}")
    for w in warnings:
        print("warning:", w)


if __name__ == "__main__":
    main()
