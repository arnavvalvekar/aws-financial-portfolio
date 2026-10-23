"""CrashLab CLI: stress the frozen decision and propose protective changes.

    python -m src.crashlab --decision runs/final/decision.json --config config.yaml

Writes runs/<run-id>/crashlab.json (the stress report + protective proposals)
and prints a readable summary. Optionally asks the scenario agent (Bedrock, via
Person B's cached llm.call_json) for extra invented shocks with --agent.

Does not touch decision.json or any A/B module; it only reads them.
"""

import argparse
import json
from pathlib import Path

from . import engine, protect, scenarios

ROOT = Path(__file__).resolve().parents[2]


def _load_config(path):
    """Reuse the backtest's config loader (yaml with a minimal fallback)."""
    from src.backtest.__main__ import load_config
    return load_config(path)


def _agent_scenarios(config, universe, use_cache=True):
    """Ask the scenario agent for extra invented shocks. Returns [] on any failure."""
    try:
        from src.agents.llm import call_json
    except Exception:
        return []
    system = (
        "You are a risk scenario designer. Propose plausible, hypothetical market "
        "shock scenarios to stress-test an existing long-only portfolio. Each shock "
        "must be grounded in a mechanism and name the positions it would hurt. Do NOT "
        "use any knowledge of how a particular future period actually turned out; "
        "these are hypotheticals. Market shock is a negative peak-to-trough number. "
        "Sector betas say how much of the market shock each sector takes "
        "(1 = with market, >1 amplified, <1 defensive, negative = benefits)."
    )
    user = (
        f"Universe: {', '.join(universe)}. Sectors: "
        f"{json.dumps(scenarios.SECTOR)}. Propose 2 distinct invented shock scenarios "
        "not already covered by: rate spike, oil shock, tech selloff, liquidity crunch, "
        "geopolitical break."
    )
    try:
        out = call_json(
            system=system, user=user, tool_name="submit_scenarios",
            schema=scenarios.SCENARIO_SCHEMA, model=config["model"],
            region=config.get("region", "us-east-1"), use_cache=use_cache,
        )
    except Exception as exc:  # network/creds/throttle — degrade to defaults
        print(f"  (scenario agent unavailable: {exc}; using default scenarios)")
        return []
    specs = []
    for s in out.get("scenarios", []):
        s.setdefault("kind", "invented")
        s.setdefault("oil_shock", None)
        s.setdefault("assumptions", "hypothetical; single sector beta; agent-proposed.")
        specs.append(s)
    return specs


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m src.crashlab", description=__doc__)
    ap.add_argument("--decision", default=str(ROOT / "runs" / "final" / "decision.json"))
    ap.add_argument("--config", default=str(ROOT / "config.yaml"))
    ap.add_argument("--metrics", default=None,
                    help="metrics.json for base-case give-up (defaults beside the decision)")
    ap.add_argument("--run-id", default="final")
    ap.add_argument("--runs-dir", default=str(ROOT / "runs"))
    ap.add_argument("--agent", action="store_true", help="also ask the scenario agent for shocks")
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args(argv)

    decision = json.loads(Path(args.decision).read_text())
    config = _load_config(args.config)
    universe = config["universe"]

    metrics = None
    metrics_path = Path(args.metrics) if args.metrics else Path(args.decision).parent / "metrics.json"
    if metrics_path.is_file():
        metrics = json.loads(metrics_path.read_text())

    specs = scenarios.all_scenarios()
    if args.agent:
        specs = specs + _agent_scenarios(config, universe, use_cache=not args.no_cache)

    reports = engine.run(decision, config, specs)
    worst_spec = next(s for s in specs if s["id"] == reports[0]["scenario"])
    proposals = protect.propose(decision, worst_spec, config, metrics)

    out_dir = Path(args.runs_dir) / args.run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "asof": decision.get("asof"),
        "n_scenarios": len(reports),
        "stress": reports,
        "protective_changes": proposals,
        "note": "Analysis beside the main result. The frozen decision is unchanged.",
    }
    (out_dir / "crashlab.json").write_text(json.dumps(payload, indent=2))

    # Readable summary.
    print(f"CrashLab — {len(reports)} scenarios on {args.decision}")
    print(f"{'scenario':24} {'kind':11} {'shock':>8}  worst culprits")
    print("-" * 78)
    for r in reports:
        culprits = ", ".join(f"{c['ticker']}({c['contribution']*100:+.1f}%)" for c in r["culprits"][:3])
        print(f"{r['label'][:24]:24} {r['kind']:11} {r['portfolio_shock']*100:7.1f}%  {culprits}")
    print()
    worst = reports[0]
    print(f"Worst: {worst['label']} at {worst['portfolio_shock']*100:.1f}% "
          f"(market {worst['market_shock']*100:.0f}%). Protective proposals:")
    for p in proposals["proposals"]:
        print(f"  - {p['change']}")
        print(f"      removes {p['shock_drawdown_removed']*100:+.2f}% shock drawdown, "
              f"gives up {p['base_case_return_given_up']*100:+.2f}% base-case return")
    print(f"\nWrote {out_dir / 'crashlab.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
