# Person A — Data & Backtest: TODO & concurrency plan

Lane owner: Person A. Branch: `personA`.
Goal (A is "done" when): one command prints total return, volatility, Sharpe and
max drawdown for the portfolio, SPY and equal weight, **and the leakage test passes**.

This file is the work breakdown for running tasks as **concurrent subagents**. It
lists every task, its dependencies, the exact files it may touch, and the interface
contract it must honor so parallel agents don't collide or drift.

---

## Status legend
- [x] done   - [~] in progress   - [ ] not started

## Progress so far
- [x] **T0 · Connectivity probe (go/no-go).** Stooq blocked (JS bot wall), FRED web
  host unreachable, FRED API needs a key. Yahoo Finance adopted for prices;
  risk-free = zero for v1 (^IRX tested fallback). README annotated.
- [x] **T1 · Prices loader + source validation.** `src/data/prices.py` (Yahoo,
  canonical schema) and `tests/test_prices_source.py` (13 tests, all pass).
  Environment pinned in `requirements.txt`; `pytest.ini` registers `network` marker.

---

## The golden rule for concurrency
**One file has exactly one owning task.** No two concurrently-running subagents may
write the same file. Shared contracts (schemas, the canonical price frame, config
keys) are **frozen below** before any parallel work starts, so agents code against a
fixed interface instead of each other's in-progress code.

If an agent discovers a contract needs changing, it must STOP and surface it — not
edit a file another agent owns.

---

## ⚠️ DESIGN-DECISION GATE — read before dispatching ANY subagent

**A (the human) makes the design decisions before an agent starts its task.** Every
task below has a **DECIDE FIRST** list: the choices A must lock before that agent is
spun out. Do not dispatch a subagent until its DECIDE FIRST items are answered and
written into the agent's prompt (or into the contract above). This keeps design
authority with A and stops agents from inventing architecture mid-task.

Workflow per task:
1. A reads the task's **DECIDE FIRST** list and records the decisions.
2. A pastes those decisions into the subagent prompt (they override defaults).
3. Only then is the agent dispatched.

Defaults are provided for each decision so A can accept-as-is quickly, but the point
is that A consciously confirms each one. If a decision changes a frozen contract
(C1-C6), update the contract first, then dispatch.

---

## Frozen interface contracts (read before coding)

### C1. Canonical price frame (produced by `src/data/prices.py`, consumed everywhere)
Long format, one row per ticker per trading day. Columns, in order:
```
ticker:str  date:datetime64[ns tz-naive]  open high low close adj_close:float  volume:Int64
```
- Sorted by `date` ascending, dates unique per ticker, no future dates.
- Returns are ALWAYS computed from `adj_close`.
- Public API (stable):
  - `fetch_prices(ticker, start=None, end=None, range_="2y", session=None, retries=3) -> DataFrame`
  - `fetch_many(tickers, start=None, end=None, range_="2y") -> DataFrame`
  - `CANONICAL_COLUMNS: list[str]`

### C2. Price store on disk (produced by T5, consumed by pit/evidence/backtest)
- Location: `data/prices/<TICKER>.csv` (e.g. `data/prices/AAPL.csv`, `data/prices/SPY.csv`).
- Each CSV = the canonical columns above, one ticker, committed (small).
- `data/raw/` is git-ignored (already in `.gitignore`); `data/prices/` IS committed.
- A manifest `data/prices/_manifest.json`: `{ "generated": ISO8601, "source":"yahoo",
  "tickers":[...], "date_min":..., "date_max":..., "rows_per_ticker":{...} }`.

### C3. Point-in-time guard (produced by T3, the ONLY door to data)
`src/pit.py`:
- `load_prices(store_dir="data/prices") -> DataFrame`  (reads C2, returns canonical frame)
- `slice(df, asof) -> DataFrame`  returns only rows with `date <= asof`.
- `slice_store(asof, store_dir="data/prices") -> DataFrame`  load + slice convenience.
- `asof` accepts str/date/Timestamp. MUST NOT mutate input. MUST raise if any
  returned row has `date > asof` (defensive self-check).
- Evidence IDs built here or by evidence modules use `px:<TICKER>:<date-iso>`.

### C4. Evidence pack (produced by T6, per SCHEMAS.md). File per analyst per run:
`runs/<run_id>/evidence/technical.json`:
```json
{ "analyst":"technical", "asof":"2026-01-30",
  "data_horizon": {"px":"2026-01-30"},
  "items":[ {"id":"px:AAPL:2026-01-30","ticker":"AAPL","date":"2026-01-30","text":"..."} ] }
```
- Nothing in `items` may have `date > asof`.
- Technical module public API:
  `build_technical_evidence(asof, universe, store_dir="data/prices") -> dict`
  (returns the pack dict; caller writes the file).
- Signals: momentum (e.g. 63d/126d return), realized volatility, drawdown,
  50-day & 200-day trend (price vs SMA, and SMA50 vs SMA200).

### C5. Backtest I/O (produced by T7)
- Reads `decision.json` (`weights`, `asof` only) + `config.yaml` + price store.
- `src/backtest/engine.py`: `run_backtest(decision, config, prices) -> BacktestResult`
  with equity curves for portfolio, SPY, equal_weight.
- `src/backtest/metrics.py`: `compute_metrics(equity_curve, rf=0.0) -> dict`
  → total_return, cagr, volatility, sharpe, max_drawdown (+dates).
- Costs: 5 bps on traded value (config `costs_bps`). Long only, 25% cap, 20% cash.
- CLI entry: `python -m src.backtest` (or `src/backtest/__main__.py`) prints the
  metrics table for portfolio / SPY / equal_weight. This is the "one command".
- Writes `runs/<run_id>/equity.csv` and `runs/<run_id>/metrics.json`.

### C6. Shared test fixtures (produced by T2, so agents don't each hit the network)
`tests/conftest.py` + `tests/fixtures/`:
- A small committed fixture price store (3-4 tickers + SPY, ~1y) so pit/evidence/
  backtest tests run offline and deterministically.
- A sample `decision.json` fixture for backtest tests.
- Fixtures let T3, T4, T6, T7 tests run WITHOUT network — essential for parallelism.

---

## Task graph (dependency waves)

Tasks in the same wave have no file overlap and no data dependency → run concurrently.

```
WAVE 0 (done):  T0 probe ─▶ T1 prices loader + source tests
                   │
WAVE 1:            ├─▶ T2 fixtures (conftest + committed fixture store + sample decision.json)
                   └─▶ T5 price store builder (writes data/prices/*.csv + manifest)
                   (T2 and T5 both only depend on T1; they touch different files → concurrent)
                   │
WAVE 2:            ├─▶ T3 pit.py guard            (needs C2 store layout + T2 fixtures)
                   │
WAVE 3:            ├─▶ T4 leakage test            (needs T3)
                   ├─▶ T6 technical evidence      (needs T3 + T2 fixtures)
                   └─▶ T7 backtest engine+metrics (needs C2 store; can start vs fixtures from T2)
                   (T4, T6, T7 touch disjoint files → concurrent once T3 exists)
                   │
WAVE 4:            └─▶ T8 integration: wire leakage test into the backtest run; one-command check
```

### Why the waves
- T3 (`pit.py`) is the single chokepoint: it defines how everything reads data, so it
  must land before T4/T6/T7 finalize. But all three can be *scaffolded* against the C3
  contract above while T3 is being written, then finished once T3 lands.
- T2 fixtures must land early (Wave 1) so Waves 2-3 agents test offline and in parallel
  without racing on the live Yahoo API.
- T5 (real price store) is independent of pit/evidence/backtest *code* — it just
  produces data — so it runs alongside T2.

---

## Tasks

- [ ] **T2 · Test fixtures & conftest**  *(Wave 1, concurrent with T5)*
  - **DECIDE FIRST (A):**
    - Which tickers + how much history in the fixture store? *(default: AAPL, MSFT,
      KO + SPY; ~1y daily — small but enough for 50d trend. Note: 200d trend needs
      more; decide whether fixture covers 200d or only shorter signals are tested
      offline while 200d is covered by a network test.)*
    - Fixtures real-but-frozen (a snapshot of Yahoo data) or hand-synthesized
      deterministic series? *(default: frozen real snapshot committed as CSV, so
      numbers are realistic; synthesized series only for metric-math unit tests.)*
    - Sample `decision.json` weights — what allocation? *(default: a valid spread
      obeying 25% cap / 20% cash across the fixture tickers, e.g. equalish + small CASH.)*
  - Depends on: T1.
  - Touches (write): `tests/conftest.py`, `tests/fixtures/prices/*.csv`,
    `tests/fixtures/decision.json`, `tests/fixtures/config.yaml` (copy of real config).
  - Must NOT touch: `src/**`, the live `data/` store.
  - Contract: expose pytest fixtures `fixture_store_dir`, `sample_decision`,
    `sample_config`. Fixture store uses the C1/C2 schema exactly.

- [ ] **T5 · Price store builder**  *(Wave 1, concurrent with T2)*
  - **DECIDE FIRST (A):**
    - History range to pull per ticker? *(default: "2y" — covers 200d pre-cutoff
      through END with margin. Confirm it reaches back far enough before 2026-01-30.)*
    - Include `^IRX` in the store? *(default: yes, fetch it but mark it non-critical;
      risk-free stays zero for v1.)*
    - CSV precision / float formatting (affects commit diffs + reproducibility)?
      *(default: write full float precision, dates as ISO `YYYY-MM-DD`.)*
    - Fail-hard or skip-and-warn if one ticker 404s? *(default: fail hard — a missing
      universe ticker breaks equal-weight; better to know immediately.)*
  - Depends on: T1.
  - Touches (write): `src/data/build_store.py`, `data/prices/*.csv`,
    `data/prices/_manifest.json`.
  - Must NOT touch: `src/data/prices.py` (import it), `tests/**`.
  - Contract: `build_store(universe, extra=["SPY"], store_dir="data/prices",
    range_="2y")` writes C2. CLI: `python -m src.data.build_store`.
  - Fetches universe + SPY (+ optionally ^IRX). Enough history for 200d trend.

- [ ] **T3 · Point-in-time guard**  *(Wave 2)*
  - **DECIDE FIRST (A):**
    - On a look-ahead violation, raise or silently drop? *(default: `slice` filters to
      `date <= asof` normally; the defensive self-check RAISES only if a later row
      somehow survives — i.e. a bug. Confirm raise-on-bug, filter-by-design.)*
    - Is `asof` inclusive of the cutoff day? *(default: YES — `date <= asof`, agents
      see the cutoff day itself. This matches README "on or before".)*
    - Should `pit` own evidence-ID construction, or only evidence modules? *(default:
      `pit` exposes a helper `px_id(ticker, date)`; evidence modules call it so the
      format lives in one place.)*
    - Trading-calendar awareness — does `slice` need to know market holidays, or is
      "whatever rows exist <= asof" enough? *(default: row-based only; no calendar
      dependency. Keeps the guard simple and vendor-agnostic.)*
  - Depends on: T1 (C1), C2 layout, T2 fixtures for its tests.
  - Touches (write): `src/pit.py`, `tests/test_pit.py`.
  - Must NOT touch: `src/data/**`, other tests.
  - Contract: C3 above. `slice` self-checks `date <= asof` and raises on violation.

- [ ] **T4 · Leakage test**  *(Wave 3, concurrent with T6, T7)*
  - **DECIDE FIRST (A):**
    - Which asof dates to property-test over? *(default: a handful spanning the data —
      e.g. 2025-06-30, 2025-09-30, the real cutoff 2026-01-30, plus an early date.)*
    - Should it also assert on the technical evidence pack (end-to-end), or only on
      `pit.slice`? *(default: BOTH — slice-level and evidence-pack-level, so leakage is
      caught wherever it enters. Requires T6 to exist; if T6 lags, ship slice-level
      first and add the evidence assertion in T8.)*
    - Run offline (fixtures) or against the real store? *(default: offline on fixtures
      for determinism; a `network`-marked variant can check the real store.)*
  - Depends on: T3.
  - Touches (write): `tests/test_no_lookahead.py`.
  - Must NOT touch: `src/**`.
  - Contract: assert `pit.slice(df, asof)` never returns `date > asof` across the
    universe; assert evidence packs built at `asof` contain no later dates; a
    property-style test over several asof dates. This test is NEVER cut (README).

- [ ] **T6 · Technical evidence**  *(Wave 3, concurrent with T4, T7)*
  - **DECIDE FIRST (A):**
    - Exact signal set + lookback windows? *(default: momentum = 63d & 126d total
      return; realized vol = 20d annualized; drawdown = peak-to-trough over trailing
      252d; trend = last close vs SMA50 & SMA200, plus SMA50-vs-SMA200 cross. Confirm
      or adjust windows.)*
    - Minimum-history policy when a ticker lacks 200 rows at asof? *(default: emit the
      signal as null/"insufficient history" rather than NaN — mirrors the analyst's
      "insufficient data" stance.)*
    - Evidence `text` wording — terse metric string or sentence? *(default: short
      sentence per ticker summarizing the signals, since B's analyst reads it.)*
    - One evidence item per ticker, or one per (ticker, signal)? *(default: one item
      per ticker with all signals in `text`; id = `px:<TICKER>:<asof-date>`.)*
  - Depends on: T3 (reads only through pit), T2 fixtures.
  - Touches (write): `src/evidence/__init__.py`, `src/evidence/technical.py`,
    `tests/test_technical.py`.
  - Must NOT touch: `src/pit.py`, `src/data/**`, `src/backtest/**`.
  - Contract: C4 above. All inputs obtained via `pit.slice`/`pit.slice_store`.

- [ ] **T7 · Backtest engine + metrics**  *(Wave 3, concurrent with T4, T6)*
  - **DECIDE FIRST (A):**
    - Rebalance for v1? *(default: `none` per config — buy at asof weights, hold to
      END. Month-end is v2/stretch.)*
    - How is CASH treated — zero return, or earns the risk-free? *(default: zero return
      for v1, consistent with risk-free = 0.)*
    - Trading days per year for annualization (vol/CAGR/Sharpe)? *(default: 252.)*
    - Sharpe risk-free input? *(default: 0.0, matching the v1 risk-free decision.)*
    - When does the 5bps cost apply? *(default: once, on initial buy at asof; with
      rebalance=none there are no further trades. Document it.)*
    - Equity curve start value? *(default: normalize all three curves to 1.0 at asof
      so they're directly comparable.)*
    - Max-drawdown tie-breaking / date reporting format? *(default: report trough date
      and the prior peak date, ISO.)*
  - Depends on: C2 store (real or fixture), sample `decision.json` (T2).
  - Touches (write): `src/backtest/__init__.py`, `src/backtest/engine.py`,
    `src/backtest/metrics.py`, `src/backtest/__main__.py`, `tests/test_backtest.py`,
    `tests/test_metrics.py`.
  - Must NOT touch: `src/pit.py`, `src/evidence/**`, `src/data/**`.
  - Contract: C5 above. Backtest reads later prices DIRECTLY (not through pit) —
    it is post-cutoff scoring, which is allowed. Only agents/evidence go through pit.
  - Verify metrics against a hand-checked tiny series in the test.

- [ ] **T8 · Integration & one-command check**  *(Wave 4, sequential, by A)*
  - **DECIDE FIRST (A):**
    - The exact "one command" surface + flags? *(default:
      `python -m src.backtest --config config.yaml --decision runs/<id>/decision.json`.)*
    - For M1, run on a fixture decision.json or wait for B's real one? *(default:
      fixture decision.json — M1 is the fallback demo on technical evidence alone.)*
    - Output format of the printed metrics table? *(default: plain-text 3-column table
      portfolio / SPY / equal_weight; also write `metrics.json`.)*
    - Does the one-command run also invoke the leakage test, or is that CI-only?
      *(default: leakage test runs in the suite; the command just produces metrics.
      README wants the leakage test "wired into every run" by Phase 3 — decide if T8
      or a later task does that wiring.)*
  - Depends on: T4, T6, T7.
  - Touches (write): `src/backtest/__main__.py` (final wiring), `README`/run notes.
  - Contract: `python -m src.backtest --config config.yaml` runs end to end on a
    decision.json (fixture is fine for M1), prints the 3-column metrics table, and
    the full test suite (incl. leakage) passes. This is the M1 fallback demo.

---

## Subagent dispatch plan (concurrency)

Run each wave as a batch of blocking subagents; wait for the wave to finish, then
launch the next. Within a wave, agents run in parallel.

- **Wave 1 (parallel):** agent-T2 (fixtures), agent-T5 (price store).
- **Wave 2 (single):** agent-T3 (pit guard). Can start in parallel with Wave 1 if it
  codes against the C2 contract and uses T2 fixtures only at test time — but safest to
  gate on T2 landing so its tests are runnable.
- **Wave 3 (parallel):** agent-T4 (leakage), agent-T6 (technical), agent-T7 (backtest).
- **Wave 4 (single):** agent-T8 (integration), run by A directly.

### Rules every subagent must follow
1. Work ONLY on your task's listed files. Never edit another task's files.
2. Import shared code; do not re-implement it. `prices.py` and `pit.py` are sources of truth.
3. Honor the frozen contracts (C1-C6). If a contract is wrong, STOP and report — do
   not change it unilaterally.
4. Add `sys.path.insert(0, ROOT)` shim in tests (see `tests/test_prices_source.py`) or
   rely on `tests/conftest.py` once T2 lands.
5. Network tests go behind `@pytest.mark.network`. Everything else must pass offline
   against fixtures.
6. Finish by running `.venv/bin/python -m pytest <your test file> -v` and report pass/fail.
7. Keep changes small; do not touch `hackathon-kit/`, `config.yaml` values, or
   `SCHEMAS.md` (B owns schemas).

### Pre-flight before dispatching (A does once)
- **Resolve the DECIDE FIRST list for each task in the wave** (see the gate at the top)
  and paste the decisions into each agent's prompt. This is the gating step.
- Confirm `requirements.txt` installed in `.venv`.
- Confirm Wave-1 agents have the C2 layout and C6 fixture spec in their prompt.
- Decide run_id convention for `runs/<run_id>/` (suggest: `dev-<asof>` for dev,
  `final` for the frozen run).

---

## Open questions to settle with the team (not blockers for A's code)
- Prices source swap Stooq→Yahoo: confirm at M0 sync (README annotated).
- Risk-free: zero for v1 vs ^IRX — A defaults to zero, disclosed in limitations.
- Dividends: `adj_close` includes dividend reinvestment; state "dividends included"
  in Results.

---

## Acceptance criteria per task (the bar each agent's tests must meet)

These are the objective "done" checks A verifies when a wave returns. They are the
SPEC the agent's own test file must satisfy — A does NOT pre-write the test code
(each task owns its test file; pre-writing would collide and pre-empt the design
gate). A re-runs the suite from the primary session and confirms each box.

### T2 · Fixtures (DONE — verified)
- [x] `tests/fixtures/prices/*.csv` for >=4 tickers + SPY, canonical C1 header
      `ticker,date,open,high,low,close,adj_close,volume`. (5 tickers, 497 rows each.)
- [x] >=200 trading rows on/before 2026-01-30 in the fixture store (318 rows → 200d OK).
- [x] `tests/fixtures/decision.json` weights sum to 1.0, obey 25% cap / 20% cash.
- [x] `conftest.py` exposes `fixture_store_dir`, `sample_decision`, `sample_config`;
      import shim present; full suite green offline.

### T5 · Price store builder
- [ ] `data/prices/<TICKER>.csv` exists for ALL 10 universe tickers + SPY, C1 schema.
- [ ] Every universe ticker has >=200 rows with date <= 2026-01-30 (200d trend ready).
- [ ] Every ticker has data through >= 2026-10-16 (END covered).
- [ ] `data/prices/_manifest.json` lists source, tickers, date_min/max, rows_per_ticker.
- [ ] `python -m src.data.build_store` reruns cleanly; fails hard on a missing ticker.

### T3 · Point-in-time guard (tests/test_pit.py)
- [ ] `slice(df, asof)` returns only rows with date <= asof (inclusive) — tested over
      several asof values against the fixture store.
- [ ] `slice` does not mutate its input frame (assert input unchanged).
- [ ] Defensive self-check RAISES if a later row survives (test via a crafted frame).
- [ ] `asof` accepts str, date, and Timestamp — all three tested.
- [ ] `slice_store(asof)` == `slice(load_prices(), asof)`.
- [ ] `px_id("AAPL", d)` == `"px:AAPL:<iso>"`.
- [ ] Passes offline: `pytest tests/test_pit.py -m "not network"`.

### T4 · Leakage test (tests/test_no_lookahead.py)
- [ ] For each of >=3 asof dates (incl. 2026-01-30), NO row from `pit.slice` has
      date > asof, across all fixture tickers.
- [ ] If `src/evidence/technical.py` exists, the evidence pack at asof contains no
      item with date > asof; else `importorskip` and note for T8.
- [ ] Runs offline, deterministic. This test is NEVER cut.

### T6 · Technical evidence (tests/test_technical.py)
- [ ] `build_technical_evidence(asof, universe, store_dir)` returns a C4-shaped dict:
      keys analyst/asof/data_horizon/items; one item per ticker.
- [ ] Every item id == `px:<TICKER>:<asof>`; no item date > asof.
- [ ] Signals computed correctly vs a hand-checked fixture ticker (at least momentum
      and an SMA cross verified numerically).
- [ ] Ticker with <200 rows → affected signals null + "insufficient history" (test by
      slicing to an early asof where history is short).
- [ ] All data obtained via `pit` (no direct CSV/Yahoo reads in the module).
- [ ] Passes offline.

### T7 · Backtest engine + metrics (tests/test_backtest.py, tests/test_metrics.py)
- [ ] `compute_metrics` matches hand-computed values on a tiny synthetic series
      (total_return, cagr, volatility, sharpe, max_drawdown + dates) within tolerance.
- [ ] `run_backtest` produces three equity curves (portfolio, SPY, equal_weight) all
      normalized to 1.0 at asof.
- [ ] Weights that breach caps are rejected or the test uses the valid sample_decision;
      CASH contributes zero return.
- [ ] 5 bps cost reduces the portfolio's starting invested value exactly once.
- [ ] CLI `python -m src.backtest --config config.yaml --decision <path>` prints a
      3-column table and writes `runs/<id>/equity.csv` + `metrics.json`.
- [ ] Backtest reads post-cutoff prices DIRECTLY (not via pit) — confirmed by code review.
- [ ] Passes offline on the fixture store.

### T8 · Integration (A, primary session)
- [x] One command runs end-to-end on a decision.json and prints portfolio/SPY/
      equal_weight metrics. (`python -m src.backtest --config config.yaml
      --decision tests/fixtures/decision.json` → 3-column table + runs/<id>/.)
- [x] FULL suite green including the leakage test: `.venv/bin/python -m pytest`
      → 66 passed (13 of them the leakage test).
- [x] No session wrote outside its allowed file list (A audited `git status`:
      only src/, tests/, data/, runs/ + planned root files changed).
- [x] Leakage test collected in the default pytest run (not network-gated), so it
      runs on every `pytest` invocation. `runs/*` git-ignored except `runs/final/`.

---

## How to run (Person A lane)

```bash
# 1. Environment (once)
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 2. (Re)build the committed price store from Yahoo — only if refreshing data
.venv/bin/python -m src.data.build_store

# 3. Run the backtest on a decision.json (M1 uses the fixture decision)
.venv/bin/python -m src.backtest \
    --config config.yaml \
    --decision tests/fixtures/decision.json
#   -> prints total return / CAGR / vol / Sharpe / max drawdown for
#      portfolio, SPY and equal_weight, and writes runs/<run_id>/{equity.csv,metrics.json}

# 4. Tests (incl. the never-cut leakage test); offline + deterministic
.venv/bin/python -m pytest            # full suite (66 tests)
.venv/bin/python -m pytest -m "not network"   # skip the live-Yahoo source tests
```

Run outputs live under `runs/<run_id>/` (dev runs git-ignored; `runs/final/`
is committed for the fresh-clone reproducibility test). When B produces the real
`decision.json`, point `--decision` at it; nothing else changes.

---
---

# PHASE 2 — Add the signals (Person A lane)  (README T+1:15 .. 2:15)

Same working model as Phase 1: this session is the primary coordinator; each task
runs as a separate Kiro session, gated by its DECIDE FIRST list, verified here
against its acceptance criteria. One owner per file. Honor the frozen contracts.

A's README Phase 2 items are **(1) FRED macro evidence with release lags** and
**(2) dashboard shell**. We ADD **(3) a crash-risk / regime evidence signal**
(the "predicting market crashes" feature) — reframed correctly below.

## ⚠️ Correctness note on the crash feature (read before building P2-3)
A forward "the market WILL crash in the scored window" predictor is LOOK-AHEAD and
is forbidden — the point-in-time valve means no agent may see past `asof`. What we
build instead is a **crash-RISK / regime-fragility indicator computed only from
data dated <= asof**: it scores how fragile the market looks *at the cutoff*
(drawdown depth, vol spike vs trailing baseline, trend break below the 200-day,
breadth/correlation). It is evidence about the present, not a forecast of the
future. It feeds the risk layer (README "Risk management → detect regime shifts")
and is covered by the leakage test like everything else. Framed this way it is
legitimate AND demo-worthy. It must NOT read any price row dated after `asof`.

## FRED reality check (affects P2-1)
FRED is blocked from this network (probe T0): web CSV host unreachable, API needs a
32-char key we don't have. So P2-1 has a DECIDE FIRST about whether macro evidence
is (a) dropped for v1 with a disclosure, (b) built from a committed/manual CSV of a
few series with release lags, or (c) sourced from Yahoo proxies (^IRX for the short
rate; ^TNX 10y; ^VIX for vol regime). Default below is (c)+(b): use Yahoo macro
proxies we CAN fetch, plus an optional committed CSV, all run through pit with lags.

---

## Frozen interface contracts (Phase 2 additions)

### C7. Macro evidence pack (produced by P2-1, contract C4 shape)
`src/evidence/macro.py` → `build_macro_evidence(asof, store_dir="data/prices") -> dict`
- Same C4 pack shape as technical: `{analyst:"macro", asof, data_horizon, items[]}`.
- Each item `{id, ticker/series, date, text}` with `date <= asof`.
- Evidence IDs: `fred:<SERIES>:<date>` if FRED-style, or reuse `px:` for Yahoo
  proxies (^IRX/^TNX/^VIX stored as price-like series). Lock the ID scheme in DECIDE.
- **Release lags:** monthly series lagged 1 month, GDP 2 months (README look-ahead
  checklist). Daily market proxies (^VIX/^TNX/^IRX) need no lag — they print same-day.
- Reads only through `src.pit` (no direct network at evidence-build time).

### C8. Crash-risk / regime evidence (produced by P2-3, contract C4 shape)
`src/evidence/regime.py` → `build_regime_evidence(asof, universe, store_dir=...) -> dict`
- C4 pack: `{analyst:"regime"|"risk", asof, data_horizon, items[]}`.
- Components (all from data <= asof): market drawdown from trailing peak, realized
  vol vs its own trailing baseline (spike ratio), fraction of universe below 200-day
  SMA (breadth/trend-break), optional ^VIX level if P2-1 lands it. Combine into a
  0..1 `crash_risk_score` + a discrete band (calm/elevated/stressed).
- One summary item for the market + optionally one per ticker; ids via `pit.px_id`
  or a new `regime:<date>` scheme (lock in DECIDE).
- NEVER reads a row dated > asof. Covered by the leakage test (extend P1 T4).

### C9. Dashboard shell (produced by P2-2)
`app/dashboard.py` (+ `app/__init__.py`).
- Reads `runs/<run_id>/metrics.json` + `equity.csv` (A's backtest outputs) and,
  if present, `decision.json` and evidence packs — NEVER recomputes prices.
- v1 is a SHELL: header strip (universe, cutoff, end, baselines, data horizon),
  an equity-curve plot (portfolio vs SPY vs equal_weight), and the metrics table.
- Decide the tech in DECIDE FIRST (Streamlit vs static matplotlib PNG+HTML vs
  plain HTML). Must run offline from committed run artifacts.
- Owns `app/**` only; does not touch src/ or tests/ of other tasks.

---

## Phase 2 task graph

```
P1 complete (prices, pit, technical, backtest, leakage) 
      │
P2 WAVE A (parallel, independent files):
      ├─▶ P2-1  src/evidence/macro.py            (+ tests/test_macro.py)
      ├─▶ P2-3  src/evidence/regime.py           (+ tests/test_regime.py)   [crash-risk]
      └─▶ P2-2  app/dashboard.py                 (+ tests/test_dashboard.py)
      (all three touch disjoint files → fully concurrent, 3 sessions)
      │
P2 WAVE B (single, A in primary session):
      └─▶ P2-4  extend tests/test_no_lookahead.py to cover macro + regime packs;
                 wire regime score into the dashboard header; integration check.
```

Max concurrency this phase: **3 sessions** (P2-1, P2-2, P2-3 in Wave A).
P2-2 (dashboard) can even start against the existing P1 run artifacts immediately.

---

## Phase 2 tasks

- [ ] **P2-1 · Macro evidence** *(Wave A, concurrent)*
  - **DECIDE FIRST (A):**
    - Macro source given FRED is blocked? *(default: Yahoo proxies we can fetch —
      ^IRX short rate, ^TNX 10y, ^VIX vol regime — stored via build_store, PLUS an
      optional committed `data/macro/*.csv` for any hand-entered series. Drop true
      FRED for v1 and DISCLOSE in limitations.)*
    - Evidence ID scheme? *(default: `px:^VIX:<date>` style for Yahoo proxies;
      reserve `fred:<SERIES>:<date>` only if a real FRED CSV is added later.)*
    - Which lags? *(default: daily market proxies = no lag; any monthly CSV series
      lagged 1 month, GDP 2 months.)*
    - Is macro on the critical path? *(default: NO — technical+regime carry M2 for A;
      macro is additive. If it stalls, ship the disclosure.)*
  - Depends on: P1 (pit, build_store). Touches (write): `src/evidence/macro.py`,
    `tests/test_macro.py`, optionally `data/macro/*.csv`. Must NOT touch other src/.

- [ ] **P2-3 · Crash-risk / regime evidence** *(Wave A, concurrent)* ← "predict crashes"
  - **DECIDE FIRST (A):**
    - Score components + weights? *(default: equal-weight blend of (i) market
      drawdown from trailing 252d peak, (ii) 20d realized-vol spike ratio vs its
      trailing 252d median, (iii) fraction of universe below 200-day SMA. Add ^VIX
      level as a 4th if P2-1 lands it.)*
    - "Market" proxy — SPY, or equal-weight of the universe? *(default: SPY.)*
    - Score shape + bands? *(default: 0..1 `crash_risk_score`; bands calm<0.33,
      elevated 0.33-0.66, stressed>0.66. Bands are descriptive, not forecasts.)*
    - ID scheme? *(default: one market item id `regime:<asof>`; per-ticker
      trend-break items use `px:<TICKER>:<asof>`.)*
    - Analyst label in the pack — "regime" or "risk"? *(default: "regime"; the risk
      agent (B) consumes it.)*
  - Depends on: P1 (pit). Touches (write): `src/evidence/regime.py`,
    `tests/test_regime.py`. Must NOT touch pit, data/, backtest, other evidence.
  - HARD RULE: no row dated > asof may be read. Test this explicitly.

- [ ] **P2-2 · Dashboard shell** *(Wave A, concurrent)*
  - **DECIDE FIRST (A):**
    - Tech choice? *(default: a self-contained matplotlib PNG + a small HTML page,
      no server — runs offline from committed artifacts, easiest for the demo and
      the fresh-clone test. Streamlit only if the team wants interactivity.)*
    - What it reads? *(default: runs/<run_id>/metrics.json + equity.csv; optional
      decision.json for the header. Never recompute prices.)*
    - Header strip contents? *(default: universe, cutoff, end, baselines, and each
      source's data horizon.)*
    - Output location? *(default: `app/out/dashboard.html` + `app/out/equity.png`;
      app/out/ git-ignored except a committed final copy under runs/final/.)*
  - Depends on: P1 backtest outputs. Touches (write): `app/__init__.py`,
    `app/dashboard.py`, `tests/test_dashboard.py`. Must NOT touch src/ or data/.

- [ ] **P2-4 · Integration & leakage extension** *(Wave B, A primary session)*
  - **DECIDE FIRST (A):** does the regime score show on the dashboard header for M2,
    or stay evidence-only? *(default: show it — it's the crash-risk headline.)*
  - Depends on: P2-1, P2-2, P2-3. Touches (write): `tests/test_no_lookahead.py`
    (extend), `app/dashboard.py` (wire regime score in). 
  - Extends the leakage test to assert macro + regime packs contain no date > asof.

---

## Phase 2 acceptance criteria

### P2-1 · Macro evidence (tests/test_macro.py)
- [ ] `build_macro_evidence(asof, store_dir)` returns a C4 pack (analyst "macro").
- [ ] Every item date <= asof; monthly/GDP series carry the documented lag.
- [ ] IDs follow the locked scheme; data_horizon present.
- [ ] All reads via pit / committed CSV — no network at build time. Offline tests pass.
- [ ] If macro is dropped for v1, the pack still returns a valid "insufficient /
      disclosed" stub rather than crashing.

### P2-3 · Crash-risk / regime evidence (tests/test_regime.py)
- [ ] `build_regime_evidence(asof, universe, store_dir)` returns a C4 pack.
- [ ] `crash_risk_score` in [0,1]; band matches the score thresholds.
- [ ] Components hand-checked on a fixture: a crafted/early asof with a known
      drawdown and a <200-SMA majority yields a HIGHER score than a calm asof.
- [ ] NO item dated > asof; explicitly tested by slicing to several asof values.
- [ ] All data via pit; offline deterministic tests pass.

### P2-2 · Dashboard shell (tests/test_dashboard.py)
- [ ] Builds from committed run artifacts WITHOUT recomputing prices or hitting net.
- [ ] Output contains the header strip, an equity curve for all three series, and
      the metrics table (assert the HTML/PNG files are produced and non-empty).
- [ ] Runs offline on the P1 `runs/<id>/` fixture; a missing optional file (e.g.
      decision.json) degrades gracefully.

### P2-4 · Integration (A primary session)
- [ ] Full suite green incl. extended leakage test covering macro + regime packs.
- [ ] Dashboard shows the crash-risk score in the header (if decided).
- [ ] `git status` audit: no session wrote outside its lane.
