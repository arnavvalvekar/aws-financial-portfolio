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
