"""Fresh-clone reproducibility check (owner C, Phase 3 / M3).

The credibility claim: a fresh clone, run with one command, produces the same
decision and the same metrics as the committed final run. This script makes that
checkable end to end.

It proves the two deterministic links that need no live model and no network:

  1. Fundamentals evidence rebuilds identically. Given the committed SEC cache,
     the fundamentals pack rebuilds byte-for-byte (no choices). Sentiment and
     geopolitics depend on whether GDELT answers (network, rate-limited) so
     their source can vary by design; they are covered by test_sentiment_geo.py,
     not by this offline claim.
  2. Decision -> metrics is deterministic. Re-scoring the committed
     runs/final/decision.json through the backtest reproduces
     runs/final/metrics.json exactly.

Full agent re-run (evidence -> five analysts -> decision) is reproducible too,
but only with the committed LLM cache or live model calls, because .llm_cache/
is git-ignored. That link is checked by the agent/orchestrator tests and by a
cache-present run; here we verify the parts that must hold on any clean clone.

Usage:
  python -m src.evidence.fresh_clone_check            # check against runs/final
  python -m src.evidence.fresh_clone_check --clone    # also git-clone this repo
                                                       # to a temp dir and check there
"""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load(p):
    return json.loads(Path(p).read_text())


def check_decision_metrics_reproduce(repo):
    """Re-score the committed decision and compare metrics to the committed ones."""
    repo = Path(repo)
    final = repo / "runs" / "final"
    if not (final / "decision.json").is_file() or not (final / "metrics.json").is_file():
        return False, "runs/final/{decision,metrics}.json missing - produce the final run first"

    committed = _load(final / "metrics.json")["metrics"]
    out_id = "repro-check"
    try:
        subprocess.run(
            [sys.executable, "-m", "src.backtest", "--config", str(repo / "config.yaml"),
             "--decision", str(final / "decision.json"), "--run-id", out_id,
             "--store-dir", str(repo / "data" / "prices")],
            cwd=repo, check=True, capture_output=True, timeout=90,
        )
    except subprocess.TimeoutExpired:
        return False, "backtest re-score timed out (missing deps in the clone? install requirements.txt)"
    except subprocess.CalledProcessError as exc:
        return False, f"backtest re-score failed: {exc.stderr.decode('utf-8', 'replace')[:200]}"
    rescored = _load(repo / "runs" / out_id / "metrics.json")["metrics"]
    subprocess.run(["rm", "-rf", str(repo / "runs" / out_id)], check=False)

    diffs = _metric_diffs(committed, rescored)
    if diffs:
        return False, f"metrics differ beyond tolerance for: {diffs}"
    return True, "decision -> metrics reproduces (within 1e-9)"


def _metric_diffs(committed, rescored, tol=1e-9):
    """Series whose metrics differ beyond a float tolerance. Dates/None compared exactly."""
    bad = []
    for series in ("portfolio", "SPY", "equal_weight"):
        c, r = committed.get(series, {}), rescored.get(series, {})
        for key in set(c) | set(r):
            cv, rv = c.get(key), r.get(key)
            if isinstance(cv, (int, float)) and isinstance(rv, (int, float)):
                if abs(float(cv) - float(rv)) > tol:
                    bad.append(f"{series}.{key}")
            elif cv != rv:
                bad.append(f"{series}.{key}")
    return bad


def check_evidence_rebuilds(repo):
    """Rebuild this lane's deterministic evidence and compare to the committed pack.

    Only the fundamentals pack is checked here: given the committed SEC cache it
    rebuilds deterministically with no choices. Sentiment and geopolitics depend
    on whether GDELT answers (network, rate-limited), so their *source* can vary
    run to run by design; they are not part of the offline reproducibility claim
    and are covered by test_sentiment_geo.py instead. This keeps the check fast
    and network-free.
    """
    import os

    repo = Path(repo)
    sys.path.insert(0, str(repo))
    import yaml

    cfg = yaml.safe_load((repo / "config.yaml").read_text())
    uni, asof = cfg["universe"], str(cfg["asof"])

    committed_path = repo / "evidence" / "fundamentals.json"
    if not committed_path.is_file():
        return [("fundamentals", None, "no committed pack")]

    raw = repo / "data" / "raw" / "sec"
    if not raw.is_dir() or not any(raw.glob("companyfacts_*.json")):
        return [("fundamentals", None, "no SEC cache (offline); covered by test_fundamentals.py")]

    from src.evidence import fundamentals  # noqa: E402

    rebuilt = fundamentals.build_pack(uni, asof)
    committed = _load(committed_path)
    same = rebuilt.get("items") == committed.get("items")
    return [("fundamentals", same, "identical" if same else "items differ")]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--clone", action="store_true", help="git-clone to a temp dir and check there")
    args = ap.parse_args(argv)

    repo = ROOT
    tmp = None
    if args.clone:
        tmp = tempfile.mkdtemp(prefix="freshclone-")
        dest = Path(tmp) / "repo"
        print(f"cloning {ROOT} -> {dest}")
        subprocess.run(["git", "clone", "--quiet", str(ROOT), str(dest)], check=True)
        repo = dest

    ok = True
    print("== decision -> metrics reproducibility ==")
    passed, msg = check_decision_metrics_reproduce(repo)
    print(f"  [{'PASS' if passed else 'FAIL'}] {msg}")
    ok = ok and passed

    print("== evidence rebuild (C lane) ==")
    for name, same, msg in check_evidence_rebuilds(repo):
        tag = "PASS" if same else ("SKIP" if same is None else "FAIL")
        print(f"  [{tag}] {name}: {msg}")
        if same is False:
            ok = False

    if tmp:
        subprocess.run(["rm", "-rf", tmp], check=False)

    print("\nRESULT:", "reproducible" if ok else "NOT reproducible")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
