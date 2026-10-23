# aws-financial-portfolio

Team build plan for Track 3 (Financial Portfolio Management) at the Austin Agentic AI Hackathon, Oct 23, 2026. Five analyst agents and a portfolio manager build a portfolio using only data dated on or before a cutoff. A backtest then scores it against what the market did next.

> Historical experiment, not financial advice or a trading recommendation.

- **Team:** three people, roles A, B and C below. Put your GitHub handle next to your role.
- **Model:** a Bedrock inference profile from the starter kit, default `us.openai.gpt-5.6-luna`, region `us-east-1`.
- **Timeline:** 4 hours, finishing at 4:00 pm. T+0:00 is the start. Drop the stretch items first when time runs short.
- **Checkpoints:** at the end of each phase everyone stops, runs `git pull --rebase`, commits and pushes, then checks the milestone before moving on.

[Get started](#get-started) · [What to aim for](#what-to-aim-for) · [Lock first](#lock-these-in-the-first-30-minutes) · [Pipeline](#how-the-pieces-connect) · [Risk management](#risk-management) · [CrashLab](#crashlab) · [Roles](#who-does-what) · [Timeline](#timeline) · [Contracts](#contracts-and-layout) · [Look-ahead checklist](#look-ahead-checklist) · [Risks](#risks-and-fallbacks) · [Demo](#three-minute-demo) · [Results](#results-and-limitations)

## Milestones

Tick these off by editing this file.

- [ ] **M0 · T+0:20.** Config and schemas committed. Three go or no-go answers reported.
- [x] **M1 · T+1:15.** One command runs end to end on technical evidence alone. This is your fallback demo.
- [x] **M2 · T+2:15.** All five analysts run on real evidence. The manager's output carries rationale, sources and triggers.
- [ ] **M3 · T+3:15.** Config, prompts and data are frozen. The final window is run once and cached.
- [ ] **M4 · T+3:30.** Code freeze. Nothing merges after this.

## Get started

Everyone does this once, in the workshop terminal where the AWS credentials are set. CLI credentials last 60 minutes, so refresh them if calls start failing.

```bash
git clone https://github.com/arnavvalvekar/aws-financial-portfolio.git
cd aws-financial-portfolio/hackathon-kit
export AWS_REGION=us-east-1
aws sts get-caller-identity
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python infer.py
```

The last command should print `OK`. The kit's own [README](hackathon-kit/README.md) has the model table, the AgentCore deploy steps and troubleshooting. Leave `hackathon-kit/` untouched and copy from it. `positron.py` is the optional Positron bootstrap from the event page, and the core build does not need it.

### Run the whole pipeline

One environment for everything, from the repo root:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python pipeline.py --run-id dev-test
```

It builds the technical evidence from the committed price store, runs the analysts on whatever packs are in `evidence/`, and scores the decision with the backtest against SPY and equal weight. Model calls are cached in `.llm_cache/`, so a repeat run is instant.

## What to aim for

The demo checklist asks for three things. State the universe, cutoff and baseline. Show the reasoning behind at least one allocation. Compare the equity curve and key metrics with the baseline. A few months of returns on ten stocks is mostly noise, so the return figure will not carry the demo. A traceable thesis and a clean test will.

Three rules:

1. **No peeking.** Nothing dated after the cutoff reaches an agent. One function, `pit.slice(asof)`, is the only way to read data, and a test fails if any date runs past the cutoff.
2. **Show the sources.** Every claim cites an evidence ID. The portfolio manager returns weights with analyst weighting, conflicts, and the triggers that would change the position. A validator rejects any ID that is not in the evidence pack.
3. **Score once.** Tune prompts on an earlier development cutoff, freeze them, then run the final window one time. Report both baselines even when the portfolio loses to them.

> [!WARNING]
> **The model may remember the window.** A Bedrock model trained past your cutoff can recall how the period played out, and that is look-ahead too. Check the training cutoff of the profile you pick (the kit lists five) and prefer a cutoff after it, even if the test window gets shorter. If you cannot, say so in the limitations. Choosing the universe has the same trap. Pick it with a rule written before you look at returns, such as the largest company in each sector at the cutoff.

## Lock these in the first 30 minutes

Put the answers in `config.yaml` and commit it. Every other task depends on them. The middle column holds proposals. Write the team's decision in the last one.

| Decision | Proposal | Decided |
| --- | --- | --- |
| Organizer rules | Ask whether the universe, cutoff or evaluation window is fixed. The brief says portfolios are evaluated against actual performance, and it also asks you to choose a cutoff. | |
| Model | The kit offers five Bedrock inference profiles: `us.openai.gpt-5.4`, `us.openai.gpt-5.5`, `us.openai.gpt-5.6-luna` (the default), `us.openai.gpt-5.6-sol` and `us.openai.gpt-5.6-terra`. Use one profile in `us-east-1`, and cache every request to disk by hash. These profiles reject the `temperature` setting (the kit sends it, so remove it), so the cache is what makes a re-run reproducible. | |
| Cutoff and window | One quarter-end trading day and a fixed end date. Example: cutoff `2026-01-30`, end `2026-10-16`. Choose the model first. A cutoff after the model's training data avoids memory leaks but leaves a shorter window. An earlier cutoff gives a longer window and needs a disclosure. | |
| Universe | Ten S&P 500 stocks across at least seven sectors, chosen by a written rule. Example: `AAPL MSFT NVDA AMZN XOM JNJ PG CAT NEE KO`. Use domestic 10-K and 10-Q filers only. Leave banks out of version 1, because their revenue tags differ. | |
| Baselines | SPY buy-and-hold, and equal weight across the same universe. The second one separates a good universe from good weighting. | |
| Decision rule | Version 1: the agents decide once at the cutoff and the portfolio is held to the end date. Version 2 (stretch): re-run at each month-end using only data up to that date. Long only, 25% cap per name, up to 20% cash, 5 bps cost on traded value. | |
| Returns | The same adjusted price series for the portfolio and both baselines. State whether dividends are included. Risk-free rate is zero or the FRED 3-month bill rate. Pick one and print it. | |
| Metrics | Total return, CAGR, volatility, Sharpe, maximum drawdown with its dates, excess return against each baseline, and contribution by position. | |

## How the pieces connect

```mermaid
flowchart LR
  subgraph KNOWN ["Known on or before the cutoff"]
    PX["Prices<br/>Yahoo Finance daily (A)<br/>Stooq blocked 2026-10-23, recheck later"]
    FR["Macro<br/>FRED series (A)"]
    SE["Filings<br/>SEC XBRL (C)"]
    GD["News tone<br/>GDELT (C)"]
    GUARD["Point-in-time guard (A)<br/>slice(asof), date ≤ cutoff"]
    EV1["Technical evidence (A)"]
    EV2["Fundamentals evidence (C)"]
    EV3["Macro evidence (A)"]
    EV4["Sentiment evidence (C)"]
    EV5["Geopolitics evidence (C)"]
    AG1["Technical analyst (B)"]
    AG2["Fundamentals analyst (B)"]
    AG3["Macro analyst (B)"]
    AG4["Sentiment analyst (B)"]
    AG5["Geopolitics analyst (B)"]
    PM["Portfolio manager (B)<br/>weights, rationale,<br/>sources, triggers"]
  end
  subgraph AFTER ["After the cutoff, scoring only"]
    LP["Later prices (A)"]
    BT["Backtest (A)<br/>fees, rebalance"]
    BL["Baselines (A)<br/>SPY, equal weight"]
    DB["Dashboard (A and C)<br/>equity curve, drawdown,<br/>metrics, reasoning"]
  end
  PX --> GUARD
  FR --> GUARD
  SE --> GUARD
  GD --> GUARD
  GUARD --> EV1
  GUARD --> EV2
  GUARD --> EV3
  GUARD --> EV4
  GUARD --> EV5
  EV1 --> AG1
  EV2 --> AG2
  EV3 --> AG3
  EV4 --> AG4
  EV5 --> AG5
  AG1 --> PM
  AG2 --> PM
  AG3 --> PM
  AG4 --> PM
  AG5 --> PM
  PM ==>|"decision.json, frozen"| BT
  LP --> BT
  BL --> BT
  BT --> DB
  classDef a fill:#E3EDF8,stroke:#1B5FA8,color:#101B26
  classDef b fill:#F5E6F0,stroke:#9B3F7E,color:#101B26
  classDef c fill:#DDF0E9,stroke:#0E7A5F,color:#101B26
  class PX,FR,GUARD,EV1,EV3,LP,BT,BL,DB a
  class AG1,AG2,AG3,AG4,AG5,PM b
  class SE,GD,EV2,EV4,EV5 c
```

The cutoff works as a one-way valve. Agents read only evidence packs built through the point-in-time guard. The one thing that crosses is `decision.json`, frozen before any later price is loaded. Later prices come from the same price store and are read by the backtest alone. The dashboard also reads `decision.json` and the analyst reports for its reasoning view. The letters show who builds each piece.

## Risk management

A risk management agent sits on top of the portfolio manager and closes the loop. In the backtest it stands in for the live risk desk, so "live portfolio" means the positions as they are carried forward through the scored window. Keep it inside the same point-in-time discipline: it reads only data dated on or before the step it is acting on, and a leakage test covers it like every other agent.

It does three things.

1. **Monitors the live portfolio.** At each step it tracks the state the positions actually reach: drawdown, realised volatility, exposure by sector and name, and how far each weight has drifted from the frozen target. It compares that state against the `change_triggers` the portfolio manager already wrote per position, so a watch is only ever against a threshold the manager committed to beforehand.
2. **Detects regime shifts.** It watches for the conditions that break the thesis, such as a rate-hike surprise from the FRED macro evidence, a geopolitical shock from the GDELT and event feeds, a volatility spike, or a trend break through the 200-day average. A shift is flagged only when the evidence crossing the line is dated on or before the current step, with its evidence ID, so the call is auditable.
3. **Triggers rebalancing.** When a regime shift fires, it hands control back to the portfolio manager for a fresh decision at that step's cutoff, under the same constraints (long only, 25% cap per name, up to 20% cash, costs on traded value). This is the version 2 month-end path with an event-driven trigger on top, so in version 1 the agent still runs and reports, it just records the trigger rather than acting on it.

The loop closes back to the portfolio manager. Each flagged shift and the rebalance it caused is logged as a dated lesson: which trigger fired, which thesis it broke, and what the manager changed in response. That log feeds back into the manager's next decision so the following portfolio avoids repeating the same mistake. Over a run this turns one-shot allocation into a system that learns from what the market did to it, within the point-in-time rules.

```mermaid
flowchart LR
  PM["Portfolio manager<br/>weights, rationale, triggers"]
  LIVE["Live portfolio<br/>carried through the window"]
  RM["Risk management agent<br/>monitor · detect · trigger"]
  LESSON["Lesson log<br/>trigger, broken thesis, response"]
  PM -->|"decision.json"| LIVE
  LIVE -->|"state vs triggers"| RM
  RM -->|"regime shift, rebalance"| PM
  RM -->|"dated lesson"| LESSON
  LESSON -->|"feeds the next decision"| PM
```

Risk and limitations: an event-driven rebalance adds trades and cost, so count every rebalance against the 5 bps cost on traded value and report how many fired. The feedback log must stay point-in-time, a lesson can only use evidence dated on or before the step that produced it, or it becomes look-ahead. In version 1 keep the agent in report-only mode so the scored result stays a single frozen decision; promote it to acting only once the month-end path is in.

Owner: B, alongside the portfolio manager and orchestration, with A wiring the monitored state out of the backtest.

## CrashLab

CrashLab stress-tests the frozen portfolio. Where the risk management agent watches the scored window as it unfolds, CrashLab asks a different question: how would these exact weights have held up under conditions far worse than the test window showed. It takes `decision.json`, replays it through a set of shock scenarios, and proposes protective changes the portfolio manager can consider.

It runs three kinds of scenario.

1. **Historical replays.** It re-prices the current weights against real crisis windows, the 2008 global financial crisis and the 2020 COVID crash to start, and reports what the portfolio would have done through each: peak-to-trough drawdown, the worst day, time to recover, and which positions did the damage. These use archived price history for the universe and SPY, read only by CrashLab after the decision is frozen, exactly like the backtest's later prices.
2. **Agent-invented shocks.** A scenario agent proposes plausible shocks the history does not cover, each as a named, parameterised stress: a rate spike of so many basis points, an oil shock, a sector-wide selloff, a liquidity crunch, a geopolitical break. Each scenario is a short JSON spec with per-factor or per-sector shocks, so the same stress can be re-applied and audited. The agent must ground each shock in a mechanism and name the positions it expects to hurt, not just pick a number.
3. **Protective changes.** From the worst scenarios it proposes concrete, constraint-respecting adjustments: trim a concentrated name, lift cash toward the 20% cap, add a diversifier, and it reports the trade-off, how much drawdown the change removes in the shock against how much expected return it gives up in the base case. These are proposals only. Any change still goes through the portfolio manager and the validator.

Point-in-time discipline still holds, with one honest caveat. CrashLab is a what-if on the frozen weights, so replaying 2008 and 2020 is allowed precisely because those windows are before the cutoff and never feed an agent's decision, they only shock an already-made portfolio. The agent-invented scenarios must be hypothetical by construction and must not encode knowledge of how the actual scored window turned out. Treat CrashLab output as analysis beside the main result, not as an input that changes the frozen `decision.json` unless you re-run the manager and say so.

```mermaid
flowchart LR
  DEC["decision.json<br/>frozen weights"]
  HIST["Historical replays<br/>2008, 2020"]
  SCEN["Scenario agent<br/>invented shocks"]
  CL["CrashLab<br/>re-price under each shock"]
  REP["Stress report<br/>drawdown, worst day,<br/>culprits per scenario"]
  PROT["Protective changes<br/>proposals, with trade-offs"]
  DEC --> CL
  HIST --> CL
  SCEN --> CL
  CL --> REP
  CL --> PROT
  PROT -.->|"optional re-run, disclosed"| DEC
```

Risk and limitations: a stress test is only as honest as its scenarios, so state the assumptions behind each one, a single beta to the shock, no correlation changes, no liquidity modelling unless added. Historical replays assume today's universe existed and behaved like its sector back then, which is a stand-in, not the real holdings of 2008. Keep the protective changes as a separate, clearly labelled variant so the headline result stays the one frozen decision. This is a stretch feature, cut it before the point-in-time guard, the baselines, or the reasoning view.

Owner: B for the scenario agent and the protective-change proposals, A for the re-pricing engine and the crisis price history. Shares the backtest's pricing and cost model.

## Who does what

The split is by layer, so each person owns different directories and rarely edits the same file. Agree the contracts below first. After that everyone can build against fixtures before real data arrives.

### A · Data and backtest

Owns the numbers. Owner: _add your GitHub handle_. Best fit: pandas and some finance math.

- **Owns:** `src/pit.py`, `src/data/prices.py`, `src/data/macro.py`, `src/evidence/technical.py`, `src/evidence/macro.py`, `src/backtest/`, `app/`, `tests/`
- **Done when:** one command prints return, volatility, Sharpe and maximum drawdown for the portfolio, SPY and equal weight, and the leakage test passes.

### B · Agents and orchestration

Owns the reasoning. Owner: _add your GitHub handle_. Best fit: prompts and the AWS SDK.

- **Owns:** `src/agents/`, `agentcore/`, `SCHEMAS.md`, `prompts/`
- **Done when:** `python run.py --config config.yaml` writes `decision.json` from real evidence, and a second run returns the identical file from cache.

### C · Evidence and story

Owns the hard data and the pitch. Owner: _add your GitHub handle_. Best fit: patience with messy data, and a good voice for the demo.

- **Owns:** `src/data/sec.py`, `src/data/gdelt.py`, `src/evidence/fundamentals.py`, `src/evidence/sentiment.py`, `src/evidence/geo.py`, the [Results and limitations](#results-and-limitations) section, and the demo script.
- **Done when:** fundamentals, sentiment and geopolitics packs exist for every ticker with a printed data horizon, and a fresh clone reproduces the final run.

### Working agreements

- One owner per directory. Ask before editing someone else's files.
- Commit small and push at least hourly. Keep `main` runnable.
- Commit derived files such as CSVs and evidence packs. Ignore raw downloads and never commit credentials.
- Hold a ten-minute sync at each milestone.

## Timeline

Times count from the start of build time. Tasks are listed per person so you can tick them off. Items marked stretch go first when time runs short.

### Phase 0 · Align (T+0:00 to 0:20, everyone)

- [ ] Make sure all three of you can push to this repo, and have everyone clone it.
- [ ] Everyone runs the kit's `infer.py` from `hackathon-kit/` (see [Get started](#get-started)).
- [ ] Add a `.gitignore` for `.venv/` and raw downloads.
- [ ] Agree `config.yaml` and the two schemas in `SCHEMAS.md`.
- [ ] Ask the organizers what is fixed.

**A**
- [x] Can Stooq and FRED files be pulled from this network? Commit the price store layout.
  <!-- NOTE (2026-10-23, A): Stooq is NOT working from the workshop network. Every
       variant (.com/.pl/http) returns HTTP 200 but serves a JavaScript anti-bot
       challenge page instead of CSV. FRED's web CSV host is unreachable (HTTP 000);
       its API host works but needs a 32-char key we don't have. We swapped prices to
       the Yahoo Finance chart API (query1/query2.finance.yahoo.com), validated by
       tests/test_prices_source.py. Macro/FRED is off the critical path (risk-free can
       be zero); ^IRX on Yahoo is a tested fallback. TODO: re-check Stooq/FRED later in
       case the network path opens up, then this swap can be revisited. -->
  <!-- Prices source now: Yahoo Finance. Risk-free: zero for v1 (^IRX fallback tested). -->


**B**
- [x] Which of the kit's five GPT profiles work in this account?
- [x] Does a forced tool call return clean JSON on the one you pick? If not, ask for JSON only and lean on the validator.
- [x] Write `SCHEMAS.md`.

**C**
- [x] Can an SEC quarterly zip be downloaded with a User-Agent header, and is GDELT reachable?
  <!-- NOTE (2026-10-23, C): SEC is reachable. company_tickers.json and the XBRL
       data.sec.gov companyfacts/companyconcept endpoints return 200 with a
       descriptive User-Agent. GDELT is NOT usable from the workshop network: the
       DOC 2.0 API returns HTTP 429 with a throttle/challenge page (shared egress IP
       is rate-limited), even at 1 request / 5s. Per the README risk table we use the
       dated event log fallback (src/evidence/events.py); src/data/gdelt.py still
       tries GDELT first and caches, so if the path opens later the packs pick it up
       automatically. Say "sentiment source: fallback" in the demo. -->
- [x] Map tickers to CIKs.
  <!-- NOTE (2026-10-23, C): ticker->CIK via SEC company_tickers.json, with a pinned
       override: the table now maps XOM to "ExxonMobil Holdings Corp" (CIK 2115436, a
       near-empty shell) instead of the operating "Exxon Mobil Corporation" (CIK
       34088). CIK_OVERRIDES in src/data/sec.py pins it. -->

> **M0 · T+0:20.** Config and schemas committed. Three go or no-go answers reported.

### Phase 1 · Walking skeleton (T+0:20 to 1:15)

**A**
- [ ] Price store for the universe and SPY, committed as small CSVs.
- [ ] `pit.slice(asof)` and the test that fails on any later date.
- [ ] Technical evidence: momentum, volatility, drawdown, 50 and 200-day trend.
- [ ] Backtest engine with both baselines and metrics.

**B**
- [x] Converse wrapper grown from the kit's `infer.py`: JSON output, a disk cache, retry with backoff, and a `maxTokens` far above the kit's 128 with a `stopReason` check.
- [x] Technical analyst and portfolio manager prompts, run on fixture evidence.
- [x] Validator: weights sum to 1, caps hold, tickers are in the universe. One re-prompt, then a deterministic repair.
- [x] Orchestrator: analysts in parallel, then the manager, with every input and output saved under `runs/<run_id>/`. It writes `decision.json`.

**C**
- [ ] SEC extraction for three tickers first, then all ten: ticker to CIK, quarterly zips up to the cutoff, only filings with a `filed` date on or before it, about ten tags with two or three candidate names each.
- [ ] First fundamentals CSV with filing dates.
- [ ] Evidence ID format for filings.

> **M1 · T+1:15.** One command runs end to end on technical evidence alone: `decision.json`, equity curve, and metrics against SPY and equal weight. This is your fallback demo.

### Phase 2 · Add the signals (T+1:15 to 2:15)

**A**
- [ ] FRED macro evidence with release lags.
- [ ] Dashboard shell: header strip, equity curve, metrics table.

**B**
- [x] Fundamentals, macro, sentiment and geopolitics analyst prompts.
- [x] Portfolio manager version 2: conflicts, analyst weighting, triggers.
- [x] Citation check: every cited ID must exist in the evidence pack.
- [x] Parallel analyst calls.

**C**
- [x] Fundamentals evidence for all tickers: growth, margins, leverage and return on equity, each with an ID.
- [x] GDELT sample for the 90 days before the cutoff (tone and event counts by theme) into sentiment and geopolitics evidence. Time-box it to 45 minutes.
- [x] Fallback if GDELT stalls: a dated event log where every row has a source published before the cutoff.
  <!-- NOTE (2026-10-23, C): GDELT returns 429 from this network (see M0 note), so
       sentiment and geopolitics are built from the dated event log. src/evidence/
       events.py holds the curated events: each row has a theme, a date <= cutoff, the
       exposed universe tickers, and a source URL. Builders: src/evidence/sentiment.py
       (one item per ticker, id gdelt:<TICKER>:<date> from GDELT or event:sentiment:
       <TICKER> fallback) and src/evidence/geo.py (id event:<theme>, plus a GDELT
       conflict-intensity read when available). Both record `source` ("gdelt"/
       "fallback"/"events"+/-gdelt) and a data_horizon. Tests: src/evidence/
       test_sentiment_geo.py. -->
- [x] A data horizon line on every evidence pack.

> **M2 · T+2:15.** All five analysts run on real evidence. The manager's output carries rationale, sources and triggers.

### Phase 3 · Inspectable and credible (T+2:15 to 3:15)

**A**
- [ ] Leakage test wired into every run.
- [ ] Contribution by position.
- [ ] Reasoning view: stances, conflicts, sources, triggers.
- [ ] Stretch: analyst scorecard.

**B**
- [x] Prompt tuning on the development cutoff only. (None done: prompts were never tuned against scored results. See runs/final/NOTES.md.)
- [x] Stretch: a risk management agent (see [Risk management](#risk-management)) that monitors the portfolio, detects regime shifts, triggers rebalancing, and feeds what it learns back to the portfolio manager. Build the plain-code checks first (position and cash caps, sector concentration, missing evidence IDs), then the LLM review. Keep it in report-only mode so the scored decision stays frozen.
- [ ] Stretch: CrashLab (see [CrashLab](#crashlab)), replay the frozen weights through 2008, 2020 and agent-invented shocks, then propose protective changes. B owns the scenario agent and proposals, A owns the re-pricing and crisis price history.
- [x] Freeze prompts and config at M3.

**C**
- [ ] Fill in [Results and limitations](#results-and-limitations).
- [ ] Set the rule for the deep-dive position, such as the largest analyst disagreement.
- [ ] Help A with the reasoning view.
- [ ] Fresh-clone test: clone, run one command, get the same `decision.json` and metrics.

> **M3 · T+3:15.** Freeze config, prompts and data. Run the final window once and cache it.

### Phase 4 · Demo (T+3:15 to 4:00, everyone)

- [x] **B:** AgentCore handler adapted from the kit's `agent.py` into `agentcore/`, deployed with the kit's direct-code-deploy commands. If it fails, demo the local runner and the kit's deployed sample.
- [ ] Rehearse twice against the checklist.
- [ ] Load the cached run so the demo makes at most one live call.
- [ ] Remove the AgentCore runtime and its dedicated role, following the kit's README.
- [ ] **A** speaks to results: curve, metrics, contribution. **B** speaks to reasoning: one decision opened up. **C** opens and closes with framing, credibility and limitations, and keeps the clock.

> **M4 · T+3:30.** Code freeze. Nothing merges after this.

## Contracts and layout

Agree these before anyone codes. They let B build agents against fixtures while A and C produce the real evidence. All values are placeholders.

**`config.yaml`**

```yaml
asof: 2026-01-30       # agents see data dated on or before this day
end: 2026-10-16        # last day scored
universe: [AAPL, MSFT, NVDA, AMZN, XOM, JNJ, PG, CAT, NEE, KO]
baselines: [SPY, equal_weight]
constraints:
  long_only: true
  max_weight: 0.25
  max_cash: 0.20
rebalance: none        # version 2: month_end
costs_bps: 5
region: us-east-1
model: us.openai.gpt-5.6-luna   # kit default. One profile, no temperature, cached
```

**Evidence IDs.** Every analyst claim lists the IDs it rests on. The validator rejects an ID that is not in that analyst's pack. A hand-built event row needs both a source and a date before the cutoff.

```text
px:<TICKER>:<date>
sec:<TICKER>:<form>:<period-end>:<tag>
fred:<SERIES>:<date>
gdelt:<theme>:<date>
event:<id>

# example
sec:CAT:10-Q:2025-09-30:OperatingIncomeLoss
```

**Analyst view, one per analyst.** Stance runs from -1 (underweight) to +1 (overweight). Confidence runs from 0 to 1.

```json
{
  "analyst": "fundamentals",
  "asof": "2026-01-30",
  "views": [{
    "ticker": "CAT",
    "stance": 0.4,
    "confidence": 0.7,
    "thesis": "One or two sentences grounded in the cited evidence.",
    "evidence": ["sec:CAT:10-Q:2025-09-30:OperatingIncomeLoss"],
    "change_triggers": ["What would flip or weaken this view"]
  }]
}
```

**Portfolio manager decision (abridged).** Weights must sum to 1 across every universe ticker plus `CASH`.

```json
{
  "asof": "2026-01-30",
  "weights": { "CAT": 0.12, "KO": 0.08, "CASH": 0.05 },
  "positions": {
    "CAT": {
      "rationale": "Why this weight, reconciling the analysts.",
      "analyst_weighting": { "technical": 0.3, "fundamentals": 0.4,
        "macro": 0.1, "sentiment": 0.1, "geopolitics": 0.1 },
      "conflicts": ["Technical bullish, fundamentals neutral"],
      "sources": ["px:CAT:2026-01-30"],
      "confidence": 0.6,
      "change_triggers": ["Close below the 200-day average"]
    }
  },
  "portfolio_thesis": "One paragraph.",
  "regime_view": "Macro stance in a sentence or two."
}
```

**Repo layout.** Letters show the owner.

```text
hackathon-kit/            starter kit as committed. Leave it untouched and copy from it
positron.py               optional Positron bootstrap, not needed for the core build
config.yaml  SCHEMAS.md  README.md (this file)
src/
  pit.py                  A   the only door to data
  data/                   A prices, macro      C sec, gdelt
  evidence/               A technical, macro   C fundamentals, sentiment, geo
  agents/                 B llm, analysts, pm, validate, orchestrate
  backtest/               A engine, metrics, attribution
app/                      A dashboard
agentcore/                B handler adapted from the kit's agent.py, plus deploy notes
runs/<run_id>/            evidence, analyst reports, decision.json, equity.csv, metrics.json
tests/                    A test_no_lookahead.py
```

## Look-ahead checklist

Run down this list before the final run. Each item is something a skeptical judge could ask about.

- [ ] **Prices.** Agents get rows dated on or before the cutoff. The backtest reads later rows and nothing else.
- [ ] **SEC filings.** Gate on the `filed` date, not the period end. Use the latest filing for each period as of the cutoff and ignore later amendments.
- [ ] **FRED.** Daily series stop at the cutoff. Lag monthly series by one month and GDP by two, which is safe against real release dates. Revisions after the cutoff are a known gap, so say so.
- [ ] **News and events.** Filter on publication date. Every row in a hand-built event log needs a source dated before the cutoff.
- [ ] **Prompts.** Tell each analyst to use only its evidence pack and to cite IDs. Scan every output for dates after the cutoff and fail the run if one appears.
- [ ] **Model memory.** Compare the model's training cutoff with yours, and state the result in the limitations.
- [ ] **Tuning.** Iterate on a development cutoff. Freeze config, prompts and data, then run the final window once.
- [ ] **Universe.** Pick it with a rule fixed before you look at returns.

## Risks and fallbacks

| Risk | What to do | Owner |
| --- | --- | --- |
| A data source is blocked or slow from the workshop network | Test every source in the first 30 minutes. If Stooq fails, use the Kaggle price datasets. They cover older periods only, so the cutoff has to move into their range. Shrink the universe before you shrink the window. | A, C |
| SEC tags differ between companies | Map two or three candidate tags per metric. Let the fundamentals analyst answer "insufficient data" instead of guessing. | C |
| GDELT is too heavy for a historical window | Sample a few files per week for the 90 days before the cutoff, or switch to the dated event log. Say which one you used. | C |
| Throttling or expired credentials | Cache every model call and limit parallel calls. CLI credentials last 60 minutes, so refresh them when calls start failing. Keep a cached final run ready for the demo. | B |
| The model returns invalid JSON or bad weights | Ask for structured output with a forced tool call if the GPT profile supports it, otherwise ask for JSON only. Validate, re-prompt once, then repair deterministically. Check `stopReason` for truncated output. | B |
| AgentCore deploy limits | The kit uses direct code deploy. Deploy its sample in the first hour, then confirm early that a multi-file package imports correctly. Keep the runtime's `requirements.txt` small and leave data-prep libraries out. Build evidence packs outside the runtime and ship them as files. If the full deploy fails, demo the local runner and show the deployed sample. | B |
| Three separate environments | If each of you has your own workshop account, share code through GitHub and not through `/workshop`. If you share one account, give each person a unique `AGENTCORE_ROLE_NAME` and runtime name, because a second role with the same name fails with `EntityAlreadyExists`. Commit small derived files, not raw zips. One owner per directory. | A, B, C |
| Integration is left to the end | Reach the walking skeleton by T+1:15. Merge to `main` at least hourly and keep it runnable. | A, B, C |
| The portfolio trails SPY | Report it. The brief asks whether the agents can explain a result and test it against the market, and beating the market is not required. | A, B, C |

## Three-minute demo

| Time | Step | Covers |
| --- | --- | --- |
| 0:00 to 0:20 | **Frame it.** Say it is a historical experiment and not financial advice. Show the universe, cutoff, end date, baselines and the data horizon of each source on one strip. | Checklist: universe, cutoff, baseline |
| 0:20 to 1:00 | **How it thinks.** Show the pipeline picture and give one sentence per analyst. | |
| 1:00 to 2:00 | **Open one decision.** Pick the position where the analysts disagree most, by that rule and not by which one won. Show each stance, how the manager reconciled them, the weight, the sources and the triggers. | Checklist: reasoning for one allocation |
| 2:00 to 2:45 | **What happened.** Show the equity curve against SPY and equal weight, then return, drawdown and Sharpe. Add contribution by position and, if built, which analyst's calls paid off. | Checklist: compare with baseline |
| 2:45 to 3:00 | **Why trust it.** Mention the leakage test, the cached reproducible run, and the limitations, including model memory. | |

## If time runs short

Cut in this order:

1. CrashLab. Keep the historical replays if the re-pricing engine already exists, cut the agent-invented scenarios first.
2. Month-end re-decisions. Keep one decision held to the end date.
3. Analyst scorecard.
4. Risk management agent. If kept, run it in report-only mode so the scored decision stays frozen.
5. Full AgentCore deploy. Keep the starter kit sample as proof of the path.
6. GDELT. Use the dated event log.
7. Positron notebook. `positron.py` is already in the repo and can stay unrun.

Never cut:

- The point-in-time guard and its test.
- Both baselines.
- Reasoning and sources on screen for at least one position.
- The limitations below.

## Results and limitations

From the frozen final run (`runs/final/`, cutoff 2026-01-30 → 2026-10-16). Reproduce exactly, with no live model call, using `./run_final.sh` (the model answers are cached in `runs/final/cache`). A plain `python pipeline.py` makes new model calls and gives a slightly different portfolio.

- **Universe and selection rule:** AAPL, MSFT, NVDA, AMZN, XOM, JNJ, PG, CAT, NEE, KO — ten S&P 500 names across seven-plus sectors, fixed from `config.yaml` before any return was looked at. Domestic 10-K/10-Q filers; banks excluded in v1 (revenue tags differ).
- **Cutoff and end date:** cutoff (asof) 2026-01-30; scored through 2026-10-16 (180 trading days).
- **Model profile:** `us.openai.gpt-5.6-luna` in `us-east-1`, one profile, no temperature, every call cached to disk.
- **Rebalance rule:** none — the agents decide once at the cutoff and the portfolio is held to the end date (v1). Long only, 25% cap per name, up to 20% cash, 5 bps on traded value.
- **Baselines:** SPY buy-and-hold, and equal weight across the same universe.
- **Deep-dive position:** chosen by rule as the largest analyst disagreement (confidence-weighted stance spread). In the final run this is **MSFT** (spread 0.78: fundamentals strongly positive +0.9, technicals strongly bearish -0.85, sentiment mildly positive +0.25), held at 8%.

| Metric | Portfolio | SPY | Equal weight |
| --- | --- | --- | --- |
| Total return | 16.74% | 11.16% | 15.55% |
| CAGR | 24.34% | 16.07% | 22.56% |
| Volatility | 9.38% | 13.27% | 10.33% |
| Sharpe | 2.37 | 1.19 | 2.02 |
| Maximum drawdown (dates) | -5.27% (2026-02-25 to 2026-03-20) | -8.87% (2026-02-02 to 2026-03-30) | -6.10% (2026-02-25 to 2026-03-20) |

Excess return: +5.57 pts over SPY, +1.19 pts over equal weight. The portfolio also carried lower volatility and a shallower drawdown than both baselines. A few months on ten names is mostly noise, so the thesis and the clean point-in-time test carry more weight than the return figure.

Stated plainly, including where the answer is "none":

- **Model memory.** The profile may have training data past the 2026-01-30 cutoff and could in principle recall how the window played out; that is a form of look-ahead the point-in-time guard cannot catch. We did not independently confirm the profile's training cutoff. Treat the result as a historical experiment, not a forecast.
- **Macro evidence is thin.** FRED was unreachable, so macro uses three Yahoo series (3-month rate, 10-year yield, VIX) plus a market crash-risk measure. There is no CPI, jobs or GDP data. These market series are not revised after release, so there is no revision gap, but the macro analyst had little to work with and answered "insufficient data" for some stocks.
- **Run-to-run variation.** These models have no temperature setting, so uncached runs differ slightly. Five uncached runs on identical evidence returned 14.9% to 16.4% (mean 15.7%): ahead of SPY in 5 of 5 and ahead of equal weight in 3 of 5. The frozen run is one draw from that spread (`runs/final/repeatability.json`, `runs/final/NOTES.md`).
- **Entry price.** The backtest buys at the close of the cutoff day, the same close the agents saw.
- **Sentiment is a curated fallback**, not measured news tone, because GDELT failed.
- **Universe size and window length.** Ten names over ~8.5 months is a small, noisy sample; metrics are indicative, not statistically robust.
- **How the universe was chosen.** By a written rule fixed before looking at returns (large-cap, sector-spread, domestic filers, no banks), not by back-fitting.
- **Cost assumption.** 5 bps on traded value at the single initial allocation; with no rebalance there are no further trading costs in v1.
- **Dividends.** Returns use the adjusted price series (dividends reinvested) for the portfolio and both baselines, consistently. Risk-free rate is zero for v1.
- **Data sources at build time.** Prices from Yahoo Finance (Stooq was blocked on the workshop network); fundamentals from SEC XBRL; sentiment and geopolitics from a dated event log (GDELT was rate-limited to HTTP 429). Each evidence pack carries a data horizon.

---

Historical experiment, not financial advice or a trading recommendation. Numbers in this section are from the frozen final run.
