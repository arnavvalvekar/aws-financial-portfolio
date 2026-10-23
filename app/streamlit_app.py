"""Streamlit dashboard for a completed run — financial-portfolio template style.

Layout follows the common Streamlit portfolio-dashboard pattern: a sidebar for
controls, a row of KPI metric cards, then tabs (Overview, Allocation, Reasoning,
Risk, Robustness, Deep dive).

Like app/dashboard.py and app/gradio_app.py, this is ARTIFACT-ONLY: it reads the
files a finished run leaves behind (metrics.json, equity.csv, decision.json,
analyst packs, risk_review.json, repeatability.json, deepdive.json) and never
loads prices, calls the model, or touches the point-in-time data layer. It cannot
change the frozen result.

Run:
    .venv/bin/streamlit run app/streamlit_app.py
    # or point at another run:  .venv/bin/streamlit run app/streamlit_app.py -- --run runs/final
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SERIES = ("portfolio", "SPY", "equal_weight")
SERIES_COLORS = {"portfolio": "#1B5FA8", "SPY": "#9B3F7E", "equal_weight": "#0E7A5F"}


# --------------------------------------------------------------------------- IO
def _read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _opt_json(path: Path) -> dict[str, Any]:
    try:
        return _read_json(path) if path.is_file() else {}
    except (OSError, ValueError, json.JSONDecodeError):
        return {}


def _read_equity(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    date_col = "date" if "date" in frame.columns else frame.columns[0]
    frame[date_col] = pd.to_datetime(frame[date_col])
    return frame.set_index(date_col).loc[:, [s for s in SERIES if s in frame.columns]]


def _coerce(raw: str) -> Any:
    v = raw.strip()
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1].strip()
        return [_coerce(p) for p in inner.split(",")] if inner else []
    if v.lower() in ("true", "false"):
        return v.lower() == "true"
    for cast in (int, float):
        try:
            return cast(v)
        except ValueError:
            pass
    return v.strip("'\"")


def _parse_config(path: Path) -> dict[str, Any]:
    """Tiny flat-YAML reader, same approach as app/dashboard.py."""
    result: dict[str, Any] = {}
    current: dict[str, Any] | None = None
    if not path.is_file():
        return result
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        indented = line[0] in (" ", "\t")
        key, _, rawval = line.strip().partition(":")
        key, value = key.strip(), rawval.strip()
        if indented and current is not None:
            current[key] = _coerce(value)
        elif value == "":
            current = {}
            result[key] = current
        else:
            result[key] = _coerce(value)
            current = None
    return result


# -------------------------------------------------------------------- formatting
def _pct(v: Any) -> str:
    return "—" if v in (None, "") else f"{float(v) * 100:.2f}%"


def _num(v: Any) -> str:
    return "—" if v in (None, "") else f"{float(v):.2f}"


def _as_text(value: Any) -> str:
    if value in (None, ""):
        return "—"
    if isinstance(value, dict):
        return ", ".join(f"{k}: {v}" for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return "\n".join(f"- {v}" for v in value) if value else "—"
    return str(value)


def _plot_equity(equity: pd.DataFrame):
    fig, ax = plt.subplots(figsize=(10, 4.6), constrained_layout=True)
    for name in equity.columns:
        ax.plot(equity.index, equity[name], linewidth=2.2, label=name,
                color=SERIES_COLORS.get(name))
    ax.set_title("Growth of $1")
    ax.set_xlabel("Date")
    ax.set_ylabel("Value")
    ax.grid(True, alpha=0.2)
    ax.legend()
    return fig


def _analyst_stances(run_dir: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    adir = run_dir / "analysts"
    if not adir.is_dir():
        return out
    for path in sorted(adir.glob("*.json")):
        payload = _opt_json(path)
        name = str(payload.get("analyst", path.stem))
        for view in payload.get("views", []):
            if isinstance(view, dict) and view.get("ticker"):
                out.setdefault(str(view["ticker"]), {})[name] = view.get("stance")
    return out


def _list_runs() -> list[str]:
    runs_dir = ROOT / "runs"
    if not runs_dir.is_dir():
        return []
    found = [p for p in runs_dir.iterdir() if p.is_dir() and (p / "metrics.json").is_file()]
    found.sort(key=lambda p: (p.name != "final", p.name))  # "final" first
    return [str(p.relative_to(ROOT)) for p in found]


# -------------------------------------------------------------------------- app
def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", default="runs/final")
    parser.add_argument("--config", default="config.yaml")
    args, _ = parser.parse_known_args(sys.argv[1:])

    st.set_page_config(page_title="Financial Portfolio Dashboard",
                       page_icon="📈", layout="wide")

    # ---- sidebar controls (template pattern) ----
    st.sidebar.title("📈 Portfolio dashboard")
    runs = _list_runs() or [args.run]
    default_idx = runs.index(args.run) if args.run in runs else 0
    run_rel = st.sidebar.selectbox("Run", runs, index=default_idx)
    run_dir = ROOT / run_rel

    config = _parse_config(ROOT / args.config)
    metrics_payload = _read_json(run_dir / "metrics.json")
    metrics = metrics_payload.get("metrics", metrics_payload)
    equity = _read_equity(run_dir / "equity.csv")
    decision = _opt_json(run_dir / "decision.json")
    meta = _opt_json(run_dir / "meta.json")
    risk = _opt_json(run_dir / "risk_review.json")
    repeat = _opt_json(run_dir / "repeatability.json")
    deepdive = _opt_json(run_dir / "deepdive.json")
    stances = _analyst_stances(run_dir)

    universe = config.get("universe") or list(decision.get("weights", {}).keys())
    cutoff = decision.get("asof", config.get("asof", "unknown"))
    end = metrics_payload.get("end", config.get("end", "unknown"))

    st.sidebar.markdown("**Run facts**")
    st.sidebar.write({
        "cutoff (asof)": str(cutoff),
        "end": str(end),
        "model": meta.get("model", config.get("model", "unknown")),
        "risk review": meta.get("risk_verdict", risk.get("verdict", "—")),
        "fixture": meta.get("fixture", False),
    })
    st.sidebar.caption("Artifact-only view. Reads a finished run; recomputes nothing.")
    st.sidebar.caption("Historical experiment, not financial advice.")

    # ---- header + KPI metric cards ----
    st.title("Multi-agent portfolio — frozen run")
    st.caption(f"Universe: {', '.join(universe) if universe else 'n/a'}  ·  "
               f"Cutoff {cutoff} → {end}  ·  Baselines: SPY, equal weight")

    p = metrics.get("portfolio", {})
    spy = metrics.get("SPY", {})
    ew = metrics.get("equal_weight", {})
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total return", _pct(p.get("total_return")),
              delta=f'{(p.get("total_return", 0) - spy.get("total_return", 0)) * 100:+.1f} pts vs SPY')
    c2.metric("Sharpe", _num(p.get("sharpe")),
              delta=f'{p.get("sharpe", 0) - spy.get("sharpe", 0):+.2f} vs SPY')
    c3.metric("Volatility", _pct(p.get("volatility")),
              delta=f'{(p.get("volatility", 0) - spy.get("volatility", 0)) * 100:+.1f} pts vs SPY',
              delta_color="inverse")
    c4.metric("Max drawdown", _pct(p.get("max_drawdown")),
              delta=f'{(p.get("max_drawdown", 0) - spy.get("max_drawdown", 0)) * 100:+.1f} pts vs SPY',
              delta_color="inverse")

    # ---- tabs ----
    tabs = st.tabs(["Overview", "Allocation", "Reasoning", "Risk", "Robustness", "Deep dive"])

    with tabs[0]:
        st.subheader("Equity curve")
        st.pyplot(_plot_equity(equity))
        st.subheader("Performance vs baselines")
        rows = []
        for label, key, fmt in [
            ("Total return", "total_return", _pct), ("CAGR", "cagr", _pct),
            ("Volatility", "volatility", _pct), ("Sharpe", "sharpe", _num),
            ("Max drawdown", "max_drawdown", _pct),
        ]:
            rows.append({"Metric": label,
                         "Portfolio": fmt(p.get(key)), "SPY": fmt(spy.get(key)),
                         "Equal weight": fmt(ew.get(key))})
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        st.info("Beats SPY on return, Sharpe and drawdown; statistically close to equal "
                "weight. Beating the market is not the point — explaining the result and "
                "testing it against the baselines is.")

    with tabs[1]:
        st.subheader("Target weights")
        weights = decision.get("weights", {})
        if weights:
            wdf = pd.DataFrame(sorted(weights.items(), key=lambda kv: -kv[1]),
                               columns=["Ticker", "Weight"]).set_index("Ticker")
            left, right = st.columns([2, 1])
            left.bar_chart(wdf)
            right.dataframe(wdf.assign(Weight=wdf["Weight"].map(lambda w: f"{w*100:.0f}%")),
                            use_container_width=True)
        contrib = metrics_payload.get("contributions")
        if contrib:
            st.subheader("Contribution by position")
            cdf = pd.DataFrame(sorted(contrib.items(), key=lambda kv: -kv[1]),
                               columns=["Ticker", "Contribution"]).set_index("Ticker")
            st.bar_chart(cdf)

    with tabs[2]:
        st.subheader("Portfolio thesis")
        st.write(_as_text(decision.get("portfolio_thesis")))
        st.subheader("Regime view")
        st.write(_as_text(decision.get("regime_view")))
        positions = decision.get("positions", {})
        if positions:
            st.subheader("Open a position")
            pick = st.selectbox("Position", list(positions.keys()),
                                index=list(positions.keys()).index(deepdive["ticker"])
                                if deepdive.get("ticker") in positions else 0)
            pos = positions.get(pick, {})
            w = weights.get(pick)
            st.markdown(f"**Weight:** {f'{w*100:.0f}%' if isinstance(w,(int,float)) else '—'}")
            if pick in stances:
                st.markdown("**Analyst stances:** " + ", ".join(
                    f"{a} {('' if s is None else f'{s:+.2f}')}" for a, s in stances[pick].items()))
            st.markdown(f"**Rationale:** {_as_text(pos.get('rationale'))}")
            st.markdown("**Conflicts:**")
            st.markdown(_as_text(pos.get("conflicts")))
            st.markdown("**Change triggers:**")
            st.markdown(_as_text(pos.get("change_triggers")))
            st.markdown(f"**Sources:** {', '.join(pos.get('sources', [])) or '—'}")
            st.markdown(f"**Confidence:** {_as_text(pos.get('confidence'))}")

    with tabs[3]:
        if risk:
            v = risk.get("verdict", "—")
            st.subheader(f"Risk review: {v}  ({risk.get('mode', 'report-only')})")
            checks = risk.get("checks", [])
            if checks:
                cdf = pd.DataFrame([
                    {"Check": c.get("name"),
                     "Passed": "✅" if c.get("passed") else "❌",
                     "Detail": c.get("detail", "")} for c in checks])
                st.dataframe(cdf, hide_index=True, use_container_width=True)
            if risk.get("lessons_used"):
                st.markdown("**Lessons fed back from earlier runs**")
                for lesson in risk["lessons_used"]:
                    st.markdown(f"- {lesson}")
            with st.expander("Per-position reasons"):
                for r in risk.get("reasons", []):
                    st.markdown(f"- {r}")
        else:
            st.info("No risk_review.json in this run.")

    with tabs[4]:
        if repeat:
            st.subheader("Repeatability (uncached runs)")
            pr = repeat.get("portfolio_return", {})
            r1, r2, r3 = st.columns(3)
            r1.metric("Mean return", _pct(pr.get("mean")))
            r2.metric("Range", f"{_pct(pr.get('min'))} – {_pct(pr.get('max'))}")
            r3.metric("Std dev", _pct(pr.get("stdev")))
            st.markdown(
                f"- Beat SPY in **{repeat.get('runs_beating_spy')}/{repeat.get('runs', '?')}** runs\n"
                f"- Beat equal weight in **{repeat.get('runs_beating_equal_weight')}/{repeat.get('runs', '?')}** runs")
            st.caption("The models have no temperature setting, so uncached runs vary. The "
                       "frozen run is one draw from this spread, kept so the demo is reproducible.")
            wr = repeat.get("weight_range")
            if wr:
                st.subheader("Weight range across runs")
                st.dataframe(pd.DataFrame(
                    [{"Ticker": k, "Min": f"{v[0]*100:.0f}%", "Max": f"{v[1]*100:.0f}%"}
                     for k, v in wr.items()]), hide_index=True, use_container_width=True)
        else:
            st.info("No repeatability.json in this run.")

    with tabs[5]:
        if deepdive:
            st.subheader(f"{deepdive.get('ticker')} — the biggest analyst disagreement")
            st.caption(deepdive.get("rule", ""))
            d1, d2, d3 = st.columns(3)
            d1.metric("Disagreement spread", _num(deepdive.get("spread")))
            d2.metric("Mean stance", _num(deepdive.get("mean_stance")))
            d3.metric("Weight", _pct(deepdive.get("weight")))
            st_ = deepdive.get("stances", {})
            if st_:
                st.bar_chart(pd.DataFrame(
                    {"stance": {a: (v if v is not None else 0) for a, v in st_.items()}}))
            st.markdown(f"**Why this weight:** {deepdive.get('rationale', '—')}")
            st.markdown("**Conflicts:**")
            st.markdown(_as_text(deepdive.get("conflicts")))
            st.markdown("**Change triggers:**")
            st.markdown(_as_text(deepdive.get("change_triggers")))
            st.markdown(f"**Sources:** {', '.join(deepdive.get('sources', [])) or '—'}")
        else:
            st.info("No deepdive.json in this run.")


if __name__ == "__main__":
    main()
