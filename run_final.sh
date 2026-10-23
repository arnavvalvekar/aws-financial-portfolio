#!/usr/bin/env bash
# The frozen final run. Model answers are cached in runs/final/cache and committed, so a fresh
# clone reproduces the same decision.json, risk review and metrics without a live model call.
set -euo pipefail
cd "$(dirname "$0")"
export LLM_CACHE_DIR="$PWD/runs/final/cache"
exec "${PYTHON:-.venv/bin/python}" pipeline.py --run-id final "$@"
