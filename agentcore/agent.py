"""AgentCore Runtime handler: runs the analyst-and-manager pipeline on the evidence packed with the deploy.

Payload (all optional): {"run_id": "...", "only": ["technical"], "use_cache": true}
Returns the decision, every analyst report, the disagreement table and any warnings.
"""

import json
import os
import shutil
import sys
import time
from pathlib import Path

# Works from the repo (agentcore/ next to src/) and from the packaged folder (src/ beside this file).
HERE = Path(__file__).resolve().parent
ROOT = next(p for p in (HERE, HERE.parent) if (p / "src" / "agents").is_dir())
sys.path.insert(0, str(ROOT))
# The runtime's code folder is read-only. /tmp is writable.
os.environ.setdefault("RUNS_DIR", "/tmp/runs")
os.environ.setdefault("LLM_CACHE_DIR", "/tmp/llm_cache")
# The frozen final run's model answers ship with the package. Copy them next to the writable cache so the
# default call returns the frozen result. Pass {"use_cache": false} for a live run.
if (ROOT / "llm_cache").is_dir():
    shutil.copytree(ROOT / "llm_cache", os.environ["LLM_CACHE_DIR"], dirs_exist_ok=True)

from bedrock_agentcore.runtime import BedrockAgentCoreApp  # noqa: E402

from src.agents.orchestrate import run  # noqa: E402

app = BedrockAgentCoreApp()


@app.entrypoint
def invoke(payload):
    payload = payload or {}
    run_id = payload.get("run_id") or "agentcore-" + time.strftime("%Y%m%d-%H%M%S")
    out, decision, warnings = run(ROOT / "config.yaml", ROOT / "evidence", run_id,
                                  payload.get("only"), payload.get("use_cache", True))
    return {
        "run_id": run_id,
        "asof": decision["asof"],
        "decision": decision,
        "analysts": {p.stem: json.loads(p.read_text()) for p in sorted((out / "analysts").glob("*.json"))},
        "disagreement": json.loads((out / "disagreement.json").read_text()),
        "risk_review": json.loads((out / "risk_review.json").read_text()) if (out / "risk_review.json").exists() else None,
        "warnings": warnings,
    }


if __name__ == "__main__":
    app.run()
