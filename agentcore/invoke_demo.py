"""Call the deployed AgentCore runtime and show it returns the frozen final decision.

    python agentcore/invoke_demo.py            # default call: the frozen run, about 5 seconds
    python agentcore/invoke_demo.py --live     # runs the models live: about a minute, slightly different answer
"""

import argparse
import json
import time
import uuid
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parent.parent
REGION = "us-east-1"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--live", action="store_true")
    p.add_argument("--name", default="portfolio_agent")
    a = p.parse_args()

    control = boto3.client("bedrock-agentcore-control", region_name=REGION)
    arn = next(r["agentRuntimeArn"] for r in control.list_agent_runtimes()["agentRuntimes"]
               if r["agentRuntimeName"] == a.name)
    print(f"runtime: {arn}")

    start = time.time()
    resp = boto3.client("bedrock-agentcore", region_name=REGION).invoke_agent_runtime(
        agentRuntimeArn=arn, runtimeSessionId=str(uuid.uuid4()) + "-demo-session",
        payload=json.dumps({"run_id": "demo", "use_cache": not a.live}).encode())
    out = json.loads(resp["response"].read())
    print(f"answered in {time.time() - start:.1f}s, asof {out['asof']}, risk review: {out['risk_review']['verdict']}")
    for t, w in sorted(out["decision"]["weights"].items(), key=lambda kv: -kv[1]):
        print(f"  {t:<6} {w:6.1%}")

    final = json.loads((ROOT / "runs" / "final" / "decision.json").read_text())
    if not a.live:
        print("identical to the frozen final run:", out["decision"] == final)


if __name__ == "__main__":
    main()
