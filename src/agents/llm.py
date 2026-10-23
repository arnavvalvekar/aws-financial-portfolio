"""Bedrock Converse wrapper: forced tool call for JSON output, disk cache, retry with backoff.

The GPT inference profiles reject the temperature setting, so reproducibility comes from the
cache: the same request returns the stored answer.
"""

import hashlib
import json
import os
import time
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = Path(os.getenv("LLM_CACHE_DIR", ROOT / ".llm_cache"))
RETRY_CODES = {
    "ThrottlingException",
    "ModelTimeoutException",
    "ServiceUnavailableException",
    "InternalServerException",
    "ModelNotReadyException",
}
_clients = {}


def _client(region):
    if region not in _clients:
        _clients[region] = boto3.client(
            "bedrock-runtime",
            region_name=region,
            config=Config(read_timeout=300, retries={"max_attempts": 1}),
        )
    return _clients[region]


def call_json(*, system, user, tool_name, schema, model, region="us-east-1",
              max_tokens=8000, use_cache=True):
    """Ask the model for one JSON object matching `schema`, returned through a forced tool call."""
    tool_config = {
        "tools": [{"toolSpec": {
            "name": tool_name,
            "description": "Submit your answer in this exact structure.",
            "inputSchema": {"json": schema},
        }}],
        "toolChoice": {"tool": {"name": tool_name}},
    }
    request = {"model": model, "system": system, "user": user,
               "tool": tool_config, "max_tokens": max_tokens}
    key = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()[:32]
    path = CACHE_DIR / f"{key}.json"
    if use_cache and path.exists():
        return json.loads(path.read_text())["output"]

    response = None
    for attempt in range(6):
        try:
            response = _client(region).converse(
                modelId=model,
                system=[{"text": system}],
                messages=[{"role": "user", "content": [{"text": user}]}],
                toolConfig=tool_config,
                inferenceConfig={"maxTokens": max_tokens},
            )
            break
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code not in RETRY_CODES or attempt == 5:
                raise
            time.sleep(min(2 ** attempt, 30))

    stop = response.get("stopReason")
    blocks = [b["toolUse"]["input"] for b in response["output"]["message"]["content"] if "toolUse" in b]
    if stop == "max_tokens":
        raise RuntimeError(f"{tool_name}: output truncated at {max_tokens} tokens. Raise max_tokens.")
    if not blocks:
        raise RuntimeError(f"{tool_name}: no tool call in the response (stopReason={stop}).")

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(
        {"request": {"model": model, "tool_name": tool_name, "max_tokens": max_tokens},
         "usage": response.get("usage", {}), "output": blocks[0]}, indent=1))
    return blocks[0]
