# AgentCore deploy (B)

Hosts the analyst-and-manager pipeline as an AgentCore Runtime. The runtime only calls the model. Evidence packs are built beforehand (`python pipeline.py` writes `evidence/technical.json`) and packed with the deploy, so nothing is downloaded inside the runtime.

The kit's own `agent.py` sends a `temperature` setting that these GPT profiles reject, so use this handler, not the kit's.

## Build the package

```bash
agentcore/build_package.sh        # copies the handler, src/agents, config.yaml and evidence/ into agentcore/dist
```

## Test it locally first (no AWS resources)

```bash
cd agentcore/dist
../../.venv/bin/pip install -q bedrock-agentcore
../../.venv/bin/python -c "import agent; print(list(agent.invoke({'run_id': 'local-test'})))"
```

## Deploy (creates a role and a runtime that cost money until removed)

Run from `agentcore/dist`, with the same environment as the kit README (`AWS_REGION=us-east-1`).

```bash
export BEDROCK_MODEL_ID=us.openai.gpt-5.6-luna
export AGENTCORE_ROLE_NAME=portfolio-agentcore-role     # unique per person if you share an account
export AGENTCORE_EXECUTION_ROLE_ARN=$(../../hackathon-kit/.venv/bin/python ../../hackathon-kit/setup_agentcore_role.py)

../../hackathon-kit/.venv/bin/agentcore configure \
  --entrypoint agent.py --name portfolio_agent --region "$AWS_REGION" \
  --deployment-type direct_code_deploy --requirements-file requirements.txt \
  --execution-role "$AGENTCORE_EXECUTION_ROLE_ARN" --disable-otel --disable-memory --non-interactive
../../hackathon-kit/.venv/bin/agentcore deploy --agent portfolio_agent
../../hackathon-kit/.venv/bin/agentcore invoke '{"run_id":"demo"}' --agent portfolio_agent
```

## Clean up when done

Delete the runtime and the role, following the kit README's cleanup notes.

## Demo invocation (deployed 2026-10-23)

Runtime `portfolio_agent` in us-east-1. The default call returns the frozen final run, byte for byte, in about 5 seconds. Pass `"use_cache": false` for a live run (about a minute, and the answer varies slightly).

```python
import boto3, json, uuid
c = boto3.client("bedrock-agentcore", region_name="us-east-1")
# ARN: aws bedrock-agentcore-control list-agent-runtimes --query "agentRuntimes[?agentRuntimeName=='portfolio_agent'].agentRuntimeArn"
r = c.invoke_agent_runtime(agentRuntimeArn=ARN, runtimeSessionId=str(uuid.uuid4()) + "-demo-session",
                           payload=json.dumps({"run_id": "demo"}).encode())
print(json.loads(r["response"].read())["decision"]["weights"])
```

Checked on deploy: the response's `decision` and `risk_review` equal `runs/final/decision.json` and `runs/final/risk_review.json`.

## Created for this deploy (delete after the demo)

- Runtime `portfolio_agent`, IAM role `portfolio-agentcore-role`, the S3 code bucket the toolkit created, and the runtime's CloudWatch log group.
