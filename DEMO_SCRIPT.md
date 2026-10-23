# Demo script (3 minutes)

The spoken text is about 380 words, which is roughly 2:30 at a normal pace. The rest of the 3:00 is the live commands. Rehearse once with a stopwatch.

Numbers come from the frozen final run in `runs/final`. If it is ever re-frozen, update them from `runs/final/NOTES.md`. Say the team name where you see `[team name]`.

## Two minutes before you go on

In a terminal in the repo folder:

```bash
git pull
./run_final.sh                                            # about 1 second, prints 16.74% / 11.16% / 15.55%
.venv/bin/python -m app.dashboard --run runs/final        # writes app/out/dashboard.html (works offline)
.venv/bin/streamlit run app/streamlit_app.py              # optional interactive version with Reasoning and Risk tabs
```

Have three things open: the deck (`presentation/portfolio-pitch.pptx`), the dashboard in a browser tab, and a terminal.

## The script

| Time | Who | On screen |
| --- | --- | --- |
| 0:00 to 0:20 | C | Slide 1 |
| 0:20 to 0:45 | B | Slide 2 (the pipeline) |
| 0:45 to 1:40 | B | Terminal: `python show_position.py MSFT` |
| 1:40 to 2:15 | A | Dashboard |
| 2:15 to 2:45 | B | Terminal: `python demo_leak_attack.py` |
| 2:45 to 3:00 | C | Slide 3 |

### 0:00 to 0:20, frame it (C)

> "We're [team name]. This is a historical experiment, not financial advice. We gave AI agents ten S&P 500 stocks and only what was known on January 30th, 2026. They built a portfolio, and we scored it on the next 180 trading days against SPY and an equal-weight mix."

### 0:20 to 0:45, how it thinks (B)

> "Five specialist agents read different evidence: prices, filings, rates, news and world events. Each scores every stock and cites its data. A portfolio manager combines them, and a risk reviewer checks the result. It all runs on Amazon Bedrock, hosted on AWS AgentCore."

### 0:45 to 1:40, one decision, opened up (B)

Run `python show_position.py MSFT` and scroll as you talk.

> "The code finds where the analysts disagree most, and that's Microsoft. Technical says strongly underweight, minus 0.85, because the stock sits below both moving averages. Fundamentals says strongly overweight, plus 0.90: revenue up 17 percent, operating income up 21. Both are 98 percent confident.
>
> The manager takes a small 8 percent position, gives technicals 55 percent of the weight, and writes down what would change its mind.
>
> Honest note: Microsoft rose 24 percent, so fundamentals were right and the hedge cost us a little."

### 1:40 to 2:15, what happened (A)

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

**Which AWS services?** Amazon Bedrock for every model call, AWS AgentCore Runtime to host the agent, IAM for its role and S3 for the deployed code.

**Is this investment advice?** No. It's a historical experiment on past data.
