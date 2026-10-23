# Schemas

The contracts between data (A, C), agents (B) and the backtest (A). All values below are placeholders. Dates use `YYYY-MM-DD`. `asof` is the cutoff.

## Model calls (B)

Probed on Oct 23: all five profiles (`us.openai.gpt-5.4`, `gpt-5.5`, `gpt-5.6-luna`, `gpt-5.6-sol`, `gpt-5.6-terra`) answer in about a second in `us-east-1`, and a forced Converse tool call returns clean JSON on every one.

- **No `temperature`.** Every profile rejects it with a `ValidationException`, and the kit's `infer.py` and `agent.py` send it. Leave it out. Reproducibility comes from the cache, not the sampler.
- Set `maxTokens` well above the kit's 128, and check `stopReason` for `max_tokens`.
- Structured output uses a forced tool call (`toolChoice: {"tool": {"name": "submit_..."}}`). The tool input schema is the JSON schema below.
- Cache every request on disk, keyed by a hash of model ID, messages and tool config, under `.llm_cache/` (git-ignored). The final run is copied to `runs/final/` and committed.

## Evidence IDs

```text
px:<TICKER>:<date>[:<metric>]
sec:<TICKER>:<form>:<period-end>:<tag>
fred:<SERIES>:<date>
gdelt:<theme>:<date>
event:<id>
```

Example: `sec:CAT:10-Q:2025-09-30:OperatingIncomeLoss`.

## Evidence pack (A and C produce, B consumes)

One file per analyst per run: `runs/<run_id>/evidence/<analyst>.json`.

```json
{
  "analyst": "fundamentals",
  "asof": "2026-01-30",
  "data_horizon": { "sec": "2026-06-26", "px": "2026-01-30" },
  "items": [
    { "id": "sec:CAT:10-Q:2025-09-30:OperatingIncomeLoss",
      "ticker": "CAT", "date": "2026-05-02", "text": "Operating income 5.1B, up 12% year on year." }
  ]
}
```

`date` is when the fact became public (filing date, release date, publication date). Nothing may be later than `asof`. `data_horizon` is the latest date per source, shown on the dashboard.

## Analyst view (B writes, one file per analyst)

`runs/<run_id>/analysts/<analyst>.json`. Analysts are `technical`, `fundamentals`, `macro`, `sentiment`, `geopolitics`.

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

- `stance` runs from -1 (underweight) to +1 (overweight). `confidence` runs from 0 to 1.
- One view per universe ticker. If the evidence is missing, use `stance: 0`, `confidence: 0` and say "insufficient data" in `thesis`.
- Every ID in `evidence` must exist in that analyst's evidence pack.

## Portfolio manager decision (B writes)

`runs/<run_id>/decision.json`. This is the only file that crosses the cutoff.

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

Validator rules (code, not prompt):

- `weights` has every universe ticker plus `CASH`, and sums to 1 within 1e-6.
- Long only, each name at most `max_weight`, `CASH` at most `max_cash` (from `config.yaml`).
- Every ID in `sources` exists in some evidence pack. No date after `asof` appears anywhere in the output.
- On failure: one re-prompt that lists the errors, then a deterministic repair (clip to caps, renormalise).

## Backtest input (A reads)

`decision.json` plus `config.yaml`. A reads only `weights` and `asof`.

## Risk review (B writes)

`runs/<run_id>/risk_review.json`. Report-only: it never changes `decision.json`.

```json
{
  "asof": "2026-01-30",
  "mode": "report-only",
  "verdict": "approve",
  "checks": [{ "name": "position_cap", "passed": true, "detail": "" }],
  "failed_checks": [],
  "reasons": ["One line per concern, naming a ticker, a check or an evidence id."],
  "concerns": [{ "ticker": "NEE", "issue": "Rationale says 9% but the weight is 10%." }],
  "adjusted_weights": null,
  "lessons_used": ["Past mistakes of this system, from earlier development runs."]
}
```

`verdict` is `approve`, `adjust` or `veto`. `adjusted_weights` is filled only for `adjust`. The code checks are position and cash caps, sector concentration, top-three concentration, positions against the analyst consensus, large positions with low confidence, unsourced positions, and crash risk against cash. Lessons come from the validator warnings of earlier development runs only (frozen in `lessons.json`), never from scored results.
