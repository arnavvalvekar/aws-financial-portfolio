# Frozen final run

Cutoff 2026-01-30, end 2026-10-16. Model `us.openai.gpt-5.6-luna`, analysts: technical, fundamentals, macro, sentiment, geopolitics. Validation warnings: 0. Risk review: **approve** (report-only).

Reproduce it exactly, with no live model calls (the answers are cached in `runs/final/cache`):

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run_final.sh
```

## Result

| | Portfolio | SPY | Equal weight |
| --- | --- | --- | --- |
| Total return | 16.74% | 11.16% | 15.55% |
| CAGR | 24.34% | 16.07% | 22.56% |
| Volatility | 9.38% | 13.27% | 10.33% |
| Sharpe | 2.37 | 1.19 | 2.02 |
| Max drawdown | -5.27% | -8.87% | -6.10% |

Weights: AAPL 14%, NVDA 12%, XOM 12%, KO 10%, JNJ 10%, MSFT 8%, CASH 8%, AMZN 8%, CAT 7%, NEE 6%, PG 5%.

Most contested positions (analyst disagreement, the deep-dive rule): MSFT, NVDA, XOM.

## How stable is it

The models have no temperature setting, so an uncached run gives a slightly different portfolio each time. Five uncached runs on identical evidence (`repeatability.json`):

- Portfolio return: mean 15.7%, range 14.9% to 16.4%, standard deviation 0.56%.
- Beat SPY (11.2%) in 5 of 5 runs.
- Beat equal weight (15.5%) in 3 of 5 runs.
- An earlier uncached run on a fresh clone returned 14.0%.

Read this as: the portfolio reliably beats SPY over this window and is statistically close to equal weight. It does not reliably beat it. The frozen run above is one draw from this spread, kept so the demo is reproducible.

## Limitations to state

- **Model memory.** The model may have been trained on data from after the cutoff and could recall how the window played out. Not controlled for.
- **Short window.** 180 trading days, one decision held to the end, ten stocks. One or two large moves can decide the comparison.
- **Sentiment evidence is a curated fallback**, not GDELT data (see `evidence/sentiment.json`, `source: fallback`).
- **Macro evidence** is three Yahoo series (3-month rate, 10-year yield, VIX) plus a market crash-risk measure, because FRED was not reachable.
- **Entry price.** The backtest buys at the cutoff day's close, the same close the agents saw.
- **Prompts were not tuned against scored results.** The analyst and manager prompts were written before any backtest ran. After the first backtest, one change was made to the manager's input: the analyst-disagreement table, added so the demo can explain contested positions, not to move returns. Other changes since then fixed validation only (citation auto-correction).
- **The risk review is report-only.** It does not change the weights.
- **Fundamentals pack** still has some repeated evidence ids and quarterly return on equity that is not annualised.
