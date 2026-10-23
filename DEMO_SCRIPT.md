# Demo script (3 minutes)

The spoken text is about 320 words, which is roughly 2:10 at a normal pace. The rest of the 3:00 is the live commands and pauses. Rehearse once with a stopwatch.

Numbers come from the frozen final run in `runs/final`. If it is ever re-frozen, update them from `runs/final/NOTES.md`. The team name is Alpha Strike.

## Two minutes before you go on

In a terminal in the repo folder:

```bash
git pull
./run_final.sh                                            # about 1 second, prints 16.74% / 11.16% / 15.55%
.venv/bin/python -m app.dashboard --run runs/final        # writes app/out/dashboard.html (works offline)
.venv/bin/streamlit run app/streamlit_app.py              # optional interactive version with Reasoning and Risk tabs
```

Have three things open: the deck (`presentation/portfolio-pitch.pptx`, five slides: title, architecture, the Microsoft decision, what happened, credibility), the dashboard in a browser tab, and a terminal.

## The script

| Time | Who | On screen |
| --- | --- | --- |
| 0:00 to 0:20 | C | Slide 1 |
| 0:20 to 1:00 | B | Slide 2 (architecture) |
| 1:00 to 1:45 | B | Slide 3 (the Microsoft decision), then the terminal: `python show_position.py MSFT` |
| 1:45 to 2:15 | A | Slide 4 (what happened), then the dashboard |
| 2:15 to 2:45 | B | Terminal: `python demo_leak_attack.py` |
| 2:45 to 3:00 | C | Slide 5 (credibility and what's next) |

### 0:00 to 0:20, frame it (C)

> "We're Alpha Strike. This is a historical experiment, not financial advice. We gave AI agents ten S&P 500 stocks and only what was known on January 30th, 2026. They built a portfolio, and we scored it on the next 180 trading days against SPY and an equal-weight mix."

### 0:20 to 1:00, how it thinks and which models (B)

> "Five specialist agents read different evidence: prices, filings, rates, news and world events. Each scores every stock and cites its data. A portfolio manager combines them, and a risk reviewer checks the result.
>
> All seven agents use the same model, GPT-5.6 Luna, through Amazon Bedrock. We tested the five GPT models Bedrock offered us, picked Luna because it was the fastest, and found that none of them accept a temperature setting. The whole pipeline is deployed as an agent on AWS AgentCore, with its IAM role and its code in S3."

### 1:00 to 1:45, one decision, opened up (B)

Run `python show_position.py MSFT` and scroll as you talk.

> "Our system found the stock the analysts argued about most: Microsoft. The chart analyst said avoid it, because the price was falling. The business analyst said buy it, because sales and profit were growing. Both were very confident.
>
> The manager split the difference with a small 8 percent bet and wrote down what would change its mind.
>
> Later, Microsoft rose 24 percent, so the business analyst was right and our caution cost us a little. That's the point: you can see exactly why it did what it did."

### 1:45 to 2:15, what happened (A)

> "The portfolio returned 16.7 percent, SPY 11.2, equal weight 15.5. Sharpe was 2.37 against 1.19 and 2.02, and the worst drop was 5.3 percent against 8.9 for SPY.
>
> Over five reruns it beat SPY every time but equal weight only three times, so the value is the explanation, not outperformance. Afterward we graded the analysts: fundamentals and technical got seven of ten directions right."

### 2:15 to 2:45, why trust it (B)

Run `python demo_leak_attack.py`. It takes under a second.

> "The big risk is peeking at the future, so we tried to cheat four ways: a future price, a direct read past the cutoff, a model writing about the future, and an invented citation. All blocked, and those are the real errors.
>
> And this final run is frozen. Anyone can reproduce it exactly in a second."

### 2:45 to 3:00, close (C)

> "Limits: 180 days, ten stocks, the model may remember 2026, and our event data is hand-curated. This is a method for testing AI investing honestly, not advice. Thank you."

## Optional extras if you have time or are asked

- `python agentcore/invoke_demo.py` calls the deployed AWS agent and prints "identical to the frozen final run: True" in a few seconds.
- `python -m src.crashlab` shows the stress test: under a 2008-style shock the portfolio would have lost about 52 percent, and it proposes trimming NVDA and AAPL into cash. It is a simple model, not a prediction.

## If you run out of time, cut in this order

1. The AgentCore call and CrashLab, which are not in the main script anyway.
2. The analyst-grading sentence.
3. The "five reruns" sentence.

Never cut the Microsoft walkthrough, the baselines comparison or the leak attack.

## If something breaks

| Problem | Do this |
| --- | --- |
| No internet or AWS | Nothing changes. `./run_final.sh`, `show_position.py`, `demo_leak_attack.py` and the static dashboard all run offline. |
| The dashboard won't open | Open `runs/final/dashboard.html` (a saved copy), or read the table from `runs/final/NOTES.md`. |
| Streamlit won't start | Use the static dashboard. |
| The AgentCore call fails | Skip it. The same agent runs locally with `./run_final.sh`. |
| Someone asks for a live re-run | `./run_final.sh --no-cache` makes live calls (about 40 seconds) and gives a slightly different answer. Say so. |

## Questions you will probably get

**Why doesn't it beat equal weight?** Over 180 days with ten stocks, one or two big moves decide that comparison. We report it as it is. The claim we can support is that it beats the market and explains itself.

**Isn't the model peeking at the future?** It may have been trained on 2026 data, and we can't rule that out. It's stated as a limitation. What we control is the data: nothing dated after January 30th reaches an agent, and the leak attack shows the guards.

**Where did the news and event data come from?** GDELT failed, so the team wrote a dated event log by hand. It has no per-item sources and was written after the fact, so it may carry hindsight. It's in the limitations. Those two analysts also scored worst in the grading.

**Why does the answer change between runs?** These models have no temperature setting, so uncached runs differ a little. That's why we froze one run, cached its answers, and report the spread over five runs.

**What stops the model making up sources?** Every citation is checked against the evidence pack. Typos are repaired, and invented ones are removed and logged.

**Did you tune it until it looked good?** No. The prompts were written before any backtest ran. One change after the first backtest, the analyst-disagreement table, was for explainability. It's written down in `runs/final/NOTES.md`.

**What if the market crashes?** CrashLab stress-tests the frozen weights. It is a simple sector-beta model, not a forecast. Its assumptions are in `runs/final/crashlab.json`.

**How did you use AWS?** Four services. Amazon Bedrock: every model call uses the Converse API, with a forced tool call so each agent returns structured JSON. We tested all five GPT inference profiles it offers, found they all work and that none accept a temperature setting, and used `us.openai.gpt-5.6-luna`. AWS AgentCore Runtime: the whole pipeline is deployed as a hosted agent, and invoking it returns the frozen result in a few seconds. IAM: a dedicated execution role limited to that one model. S3 and CloudWatch: the toolkit stores the deployed code in S3 and the runtime logs to CloudWatch.

**Which model did you use, and why?** GPT-5.6 Luna on Amazon Bedrock, for all seven agents: five analysts, the manager and the risk reviewer. The workshop kit offered five GPT profiles (5.4, 5.5, 5.6 Luna, Sol and Terra). We probed all five for access, speed and structured output. They all worked, and Luna was the fastest, so we used it. We did not compare portfolio quality across models, only whether each one worked.

**Why the same model for every agent?** Simplicity and reproducibility. The downside is that the agents can share the same blind spots. Using a different model for the risk reviewer would make that check more independent, and it's a next step we didn't build.

**Why Bedrock and not calling a model directly?** One managed API for several models, access through the workshop's IAM role with no API keys in the code, and it let us compare five model profiles by changing one setting.

**Is this investment advice?** No. It's a historical experiment on past data.
