# Demo script (3 minutes)

Numbers come from the frozen final run in `runs/final`. If the final run is ever re-frozen, update the numbers below from `runs/final/NOTES.md`.

## Two minutes before you go on

Run these in a terminal in the repo folder, with the project environment (`.venv`):

```bash
git pull
./run_final.sh                                   # about 1 second, prints 16.74% / 11.16% / 15.55%
.venv/bin/python -m app.dashboard --run runs/final   # writes app/out/dashboard.html, open it in a browser
```

Have three things ready on screen: the pitch deck (`presentation/portfolio-pitch.pptx`), the dashboard in a browser tab, and a terminal.

## The script

| Time | Who | On screen |
| --- | --- | --- |
| 0:00 to 0:20 | C | Slide 1 |
| 0:20 to 0:50 | B | Slide 2 (the pipeline) |
| 0:50 to 1:50 | B | Terminal: `python show_position.py MSFT` |
| 1:50 to 2:25 | A | Dashboard tab |
| 2:25 to 2:50 | B | Terminal: `python demo_leak_attack.py` |
| 2:50 to 3:00 | C | Slide 1 or 3 |

### 0:00 to 0:20, frame it (C)

> "This is a historical experiment, not financial advice. We gave a team of AI agents ten S&P 500 stocks and only the information that existed on January 30th, 2026. They built a portfolio. Then we scored it on what actually happened over the next 180 trading days, up to October 16th, against two baselines: the S&P 500 fund SPY, and simply holding all ten stocks in equal amounts."

### 0:20 to 0:50, how it thinks (B)

> "Five specialist agents each read a different kind of evidence: price trends, company filings, interest rates and volatility, news mood, and world events. Each one scores every stock from minus one to plus one, and has to cite the exact data behind its view. A portfolio manager agent then combines those five opinions into weights for the ten stocks plus cash. A risk reviewer checks the result. All of it runs on Amazon Bedrock, and the whole thing is deployed as an agent on AWS AgentCore."

### 0:50 to 1:50, one decision, opened up (B)

Run `python show_position.py MSFT`. Scroll as you talk.

> "We didn't pick a flattering example. The code measures where the analysts disagree most, and Microsoft is number one.
>
> The technical analyst says strongly underweight: minus 0.85, 98 percent confident. Microsoft was below both its moving averages with a death cross.
>
> The fundamentals analyst says strongly overweight: plus 0.90, also 98 percent confident. Revenue up 16.7 percent, operating income up 20.9, cash flow up 60.
>
> Sentiment is mildly positive. Macro and geopolitics had nothing about Microsoft, so they said 'insufficient data' instead of guessing.
>
> The manager's answer is a small position, 8 percent. It gave the technicals 55 percent of the influence and fundamentals 35, and it wrote down what would change its mind: add if the stock reclaims its 200-day average, cut if operating margin drops below 45 percent. Every number traces back to a specific piece of evidence.
>
> Here is the honest part. Microsoft actually rose about 24 percent in this window, so the fundamentals analyst was right and the hedge cost us a little. We're not claiming the agents are smart. We're showing exactly why they did what they did, and you can check every step."

### 1:50 to 2:25, what happened (A)

> "Over the 180 days the portfolio returned 16.7 percent. SPY returned 11.2. Equal weight returned 15.5. The Sharpe ratio, which is return for the risk taken, was 2.37 against 1.19 and 2.02. The worst drop was 5.3 percent, against 8.9 for SPY and 6.1 for equal weight. The biggest contributors were Apple, Exxon and Coca-Cola. We also graded each analyst afterward: the fundamentals and technical analysts got the direction right on 7 of 10 stocks, and the sentiment and geopolitics analysts were weak. With ten stocks that is a hint, not proof.
>
> We reran the whole pipeline five times from scratch. It beat SPY every time. It beat equal weight in only three of the five, with returns between 14.9 and 16.4 percent. So the honest summary: it beats the market and it's close to equal weight. The real value here is the explanation, not outperformance."

### 2:25 to 2:50, why trust it (B)

Run `python demo_leak_attack.py` (it takes under a second; use `--pause` to narrate each attack).

> "The biggest risk in testing an AI on history is that it peeks at the future. So we tried to cheat four ways. We put a future price in the evidence: blocked. We read the price store directly past the cutoff: blocked. We made the model write about a date after the cutoff: blocked, the run stops. We made it cite evidence that doesn't exist: removed. Every message you see is the real error from the real code.
>
> And the final run is frozen. Anyone can clone this repo and reproduce this exact portfolio in a second, with no model call."

Optional, 10 seconds if time allows: `python agentcore/invoke_demo.py` shows the deployed AWS agent returning the same decision, "identical to the frozen final run: True".

### 2:50 to 3:00, close (C)

> "The limits: 180 days, ten stocks, the model may remember some of 2026, and our sentiment data is a curated fallback. This is a method for testing AI investment reasoning honestly, not advice. Thank you."

## If you run out of time, cut in this order

1. The AgentCore call.
2. The analyst-grading sentence.
3. The "five reruns" sentence.
4. The sentiment, macro and geopolitics lines in the Microsoft segment.

Never cut the Microsoft walkthrough, the baselines comparison or the leak attack.

## If something breaks

| Problem | Do this |
| --- | --- |
| No internet or AWS | Nothing changes. `./run_final.sh`, `show_position.py`, `demo_leak_attack.py` and the dashboard all run offline. |
| The dashboard won't open | Open `app/out/equity.png`, or read the table from `runs/final/NOTES.md`. |
| The AgentCore call fails | Skip it, and say the same agent runs locally with `./run_final.sh`. |
| Someone asks to re-run live | `./run_final.sh --no-cache` makes live calls (about 40 seconds) and gives a slightly different answer. Say so. |

## Questions you will probably get

**Why doesn't it beat equal weight?** Over 180 days with ten stocks, one or two big moves decide that comparison. We report it as it is. The claim we can support is that it beats the market and explains itself.

**Isn't the model peeking at the future?** It may have been trained on 2026 data, and we can't rule that out. We state it as a limitation. What we do control is the data: nothing dated after January 30th reaches an agent, and the leak attack shows the guards.

**Why does the answer change between runs?** These models have no temperature setting, so every uncached run differs a little. That's why we froze one run and cached its answers, and why we report the spread over five runs.

**What stops the model making up sources?** Every citation is checked against the evidence pack. Typos are repaired, and invented ones are removed and logged.

**Did you tune it until it looked good?** No. The prompts were written before any backtest ran. One change after the first backtest, the analyst-disagreement table, was for explainability. It's written down in `runs/final/NOTES.md`.

**Which AWS services?** Amazon Bedrock for every model call, and AWS AgentCore Runtime to host the agent, with IAM for its role and S3 for the deployed code.

**Is this investment advice?** No. It's a historical experiment on past data.
