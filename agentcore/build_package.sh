#!/usr/bin/env bash
# Pack the handler, the agent code, the config and the evidence into agentcore/dist for deploy.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
root="$(dirname "$here")"
dist="$here/dist"

rm -rf "$dist"
mkdir -p "$dist/src"
cp "$here/agent.py" "$here/requirements.txt" "$dist/"
cp -r "$root/src/agents" "$dist/src/agents"
find "$dist" -name __pycache__ -prune -exec rm -rf {} +
cp "$root/config.yaml" "$dist/"
cp -r "$root/evidence" "$dist/evidence"
echo "package ready in $dist"
