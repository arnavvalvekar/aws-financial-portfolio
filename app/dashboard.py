"""Render a static equity curve and metrics dashboard from a completed run.

This module deliberately consumes only the artifacts produced by the backtest:
``metrics.json`` and ``equity.csv``.  It does not load prices, invoke the point-
in-time data layer, or make network requests.
"""
from __future__ import annotations

import argparse
import base64
import html
import json
from pathlib import Path
from typing import Any

import matplotlib

# The dashboard is intended to work in the headless workshop environment.
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

SERIES = ("portfolio", "SPY", "equal_weight")
METRIC_ROWS = (
    ("Total return", "total_return", "percent"),
    ("CAGR", "cagr", "percent"),
    ("Volatility", "volatility", "percent"),
    ("Sharpe", "sharpe", "number"),
    ("Max drawdown", "max_drawdown", "percent"),
    ("Drawdown peak", "max_drawdown_peak", "date"),
    ("Drawdown trough", "max_drawdown_trough", "date"),
)


# This small parser mirrors the project's fixture/backtest parser.  The
# workshop venv intentionally has no YAML dependency, and the project config
# is a flat mapping plus the constraints mapping and inline lists.
def _coerce(raw: str) -> Any:
    value = raw.strip()
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        return [_coerce(part) for part in inner.split(",")] if inner else []
    if value.lower() in ("true", "false"):
        return value.lower() == "true"
    for cast in (int, float):
        try:
            return cast(value)
        except ValueError:
            pass
    return value.strip("'\"")


def _parse_config(path: str | Path) -> dict[str, Any]:
    result: dict[str, Any] = {}
    current_map: dict[str, Any] | None = None
    with Path(path).open(encoding="utf-8") as config_file:
        for raw_line in config_file:
            line = raw_line.split("#", 1)[0].rstrip()
            if not line.strip():
                continue
            indented = line[0] in (" ", "\t")
            key, _, raw_value = line.strip().partition(":")
            key, value = key.strip(), raw_value.strip()
            if indented and current_map is not None:
                current_map[key] = _coerce(value)
            elif value == "":
                current_map = {}
                result[key] = current_map
            else:
                result[key] = _coerce(value)
                current_map = None
    return result


def _read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as source:
        payload = json.load(source)
    if not isinstance(payload, dict):
        raise ValueError(f"expected a JSON object in {path}")
    return payload


def _read_equity(path: Path) -> pd.DataFrame:
    """Read the backtest curve without doing any price or return calculations."""
    frame = pd.read_csv(path)
    date_column = "date" if "date" in frame.columns else frame.columns[0]
    frame[date_column] = pd.to_datetime(frame[date_column])
    frame = frame.set_index(date_column)
    missing = [name for name in SERIES if name not in frame.columns]
    if missing:
        raise ValueError(f"equity.csv is missing series: {', '.join(missing)}")
    return frame.loc[:, list(SERIES)]


def _plot_equity(equity: pd.DataFrame, output: Path) -> None:
    # Deliberate series colors: portfolio is the subject (ink/teal, heaviest),
    # baselines are quieter references. No default matplotlib tab10 palette.
    style = {
        "portfolio": {"color": "#0F7B8A", "lw": 2.6, "z": 3},
        "SPY": {"color": "#8A98A8", "lw": 1.6, "z": 2},
        "equal_weight": {"color": "#C2B280", "lw": 1.6, "z": 2},
    }
    figure, axis = plt.subplots(figsize=(10, 4.8), constrained_layout=True)
    figure.patch.set_facecolor("#FFFFFF")
    axis.set_facecolor("#FFFFFF")
    for name in SERIES:
        s = style[name]
        axis.plot(equity.index, equity[name], color=s["color"],
                  linewidth=s["lw"], zorder=s["z"], label=name,
                  solid_capstyle="round")
    axis.axhline(1.0, color="#C8D1DC", linewidth=1, zorder=1)
    axis.set_ylabel("Growth of $1", color="#5A6B7F", fontsize=11)
    axis.grid(True, axis="y", color="#E6EBF1", linewidth=1)
    axis.set_axisbelow(True)
    for spine in ("top", "right"):
        axis.spines[spine].set_visible(False)
    for spine in ("left", "bottom"):
        axis.spines[spine].set_color("#C8D1DC")
    axis.tick_params(colors="#5A6B7F", labelsize=10)
    legend = axis.legend(frameon=False, loc="upper left", fontsize=10)
    for text in legend.get_texts():
        text.set_color("#0E1726")
    figure.savefig(output, dpi=150, format="png")
    plt.close(figure)


def _format_value(value: Any, kind: str) -> str:
    if value is None or value == "":
        return "—"
    if kind == "percent":
        return f"{float(value) * 100:.2f}%"
    if kind == "number":
        return f"{float(value):.3f}"
    return str(value)


def _metrics_table(metrics: dict[str, Any]) -> str:
    rows: list[str] = []
    for label, key, kind in METRIC_ROWS:
        cells = [f"<th scope=\"row\">{html.escape(label)}</th>"]
        for series in SERIES:
            value = metrics.get(series, {}).get(key)
            cls = "num"
            if series == "portfolio":
                cls += " col-portfolio"
            # Sign coloring only for signed numeric kinds (returns, sharpe, dd).
            if kind in ("percent", "number") and value not in (None, ""):
                try:
                    fv = float(value)
                    cls += " pos" if fv > 0 else " neg" if fv < 0 else ""
                except (TypeError, ValueError):
                    pass
            cells.append(
                f'<td class="{cls.strip()}">{html.escape(_format_value(value, kind))}</td>'
            )
        rows.append("<tr>" + "".join(cells) + "</tr>")
    headers = "".join(
        f'<th scope="col" class="{"col-portfolio" if name == "portfolio" else ""}">'
        f"{html.escape(name)}</th>"
        for name in SERIES
    )
    return (
        '<table class="metrics">'
        f"<thead><tr><th scope=\"col\">Metric</th>{headers}</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def _regime_summary(run_dir: Path) -> str | None:
    """Back-compat string form of the regime reading (kept for callers/tests)."""
    data = _regime_reading(run_dir)
    if not data:
        return None
    parts = []
    if data.get("score") is not None:
        parts.append(f"score {data['score']}")
    if data.get("band") is not None:
        parts.append(f"band {data['band']}")
    return " · ".join(parts) or None


def _regime_reading(run_dir: Path) -> dict[str, Any] | None:
    """Read the crash-risk / regime pack beside the run and return its score and
    band for the hero gauge. Artifact-only: reads run_dir/evidence/regime.json,
    never recomputes. Returns None if absent."""
    pack_path = run_dir / "evidence" / "regime.json"
    if not pack_path.is_file():
        return None
    try:
        pack = _read_json(pack_path)
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    items = pack.get("items") or []
    if not items:
        return None
    text = str(items[0].get("text", ""))
    score = band = None
    for token in text.replace(";", " ").split():
        if token.startswith("crash_risk_score="):
            try:
                score = float(token.split("=", 1)[1])
            except ValueError:
                score = None
        elif token.startswith("band="):
            band = token.split("=", 1)[1]
    if score is None and band is None:
        return None
    return {"score": score, "band": band}


_BAND_COLOR = {"calm": "#1F9D6B", "elevated": "#D98A1F", "stressed": "#C8453B"}


def _data_horizon(
    run_dir: Path, metrics_payload: dict[str, Any], decision: dict[str, Any] | None, cutoff: str
) -> str:
    """Find an available horizon, with a truthful artifact-only fallback."""
    candidates = [
        (decision or {}).get("data_horizon"),
        metrics_payload.get("data_horizon"),
    ]
    for candidate in candidates:
        if isinstance(candidate, dict) and candidate:
            parts = [f"{key}: {value}" for key, value in candidate.items()]
            return ", ".join(parts)
        if isinstance(candidate, str) and candidate:
            return candidate

    # Evidence packs are optional, but if already committed alongside the run,
    # include their declared horizons without reading any underlying data.
    evidence_dir = run_dir / "evidence"
    horizons: list[str] = []
    if evidence_dir.is_dir():
        for evidence_path in sorted(evidence_dir.glob("*.json")):
            try:
                evidence = _read_json(evidence_path)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            horizon = evidence.get("data_horizon")
            if isinstance(horizon, dict):
                horizons.extend(f"{key}: {value}" for key, value in horizon.items())
    if horizons:
        return ", ".join(dict.fromkeys(horizons))
    return f"through cutoff ({cutoff})"


def _reasoning_text(value: Any) -> str:
    """Convert an artifact value to escaped display text without interpreting it."""
    if value is None or value == "":
        return "—"
    if isinstance(value, dict):
        value = ", ".join(f"{key}: {item}" for key, item in value.items())
    elif isinstance(value, (list, tuple)):
        value = ", ".join(str(item) for item in value) or "—"
    return html.escape(str(value))


# Friendly names for common SEC XBRL tags; falls back to a de-camel-cased form.
_SEC_TAG_LABELS = {
    "RevenueFromContractWithCustomerExcludingAssessedTax": "Revenue",
    "Revenues": "Revenue",
    "OperatingIncomeLoss": "Operating income",
    "NetIncomeLoss": "Net income",
    "NetCashProvidedByUsedInOperatingActivities": "Operating cash flow",
    "StockholdersEquity": "Stockholders' equity",
    "Assets": "Total assets",
    "Liabilities": "Total liabilities",
    "GrossProfit": "Gross profit",
    "EarningsPerShareDiluted": "Diluted EPS",
    "ResearchAndDevelopmentExpense": "R&D expense",
    "LongTermDebtNoncurrent": "Long-term debt",
}

_SOURCE_GROUP_LABEL = {
    "px": "Price", "sec": "SEC", "fred": "Macro",
    "gdelt": "News", "event": "Event", "regime": "Regime",
}


def _decamel(text: str) -> str:
    out = []
    for i, ch in enumerate(text):
        if ch.isupper() and i and not text[i - 1].isupper():
            out.append(" ")
        out.append(ch)
    return "".join(out).strip()


def _decode_source(sid: str) -> tuple[str, str]:
    """Decode an evidence ID into (group, human-readable label). The full ID is
    preserved by the caller as a tooltip for auditability."""
    parts = sid.split(":")
    kind = parts[0]
    if kind == "px" and len(parts) >= 3:
        return "px", f"{parts[1]} · {parts[2]}"
    if kind == "sec" and len(parts) >= 5:
        tag = parts[4]
        label = _SEC_TAG_LABELS.get(tag, _decamel(tag))
        return "sec", f"{parts[2]} {parts[3]} · {label}"
    if kind == "fred" and len(parts) >= 3:
        return "fred", f"{parts[1]} · {parts[2]}"
    if kind == "gdelt" and len(parts) >= 3:
        return "gdelt", f"{parts[1]} · {parts[2]}"
    if kind == "event":
        body = ":".join(parts[1:])
        # "sentiment:AAPL" -> "Sentiment: AAPL"; "interest-rates" -> "Interest rates"
        if ":" in body:
            theme, _, subj = body.partition(":")
            return "event", f"{_decamel(theme.replace('-', ' ')).capitalize()}: {subj}"
        return "event", _decamel(body.replace("-", " ")).capitalize()
    if kind == "regime":
        return "regime", ":".join(parts[1:])
    return kind, sid


def _sources_html(value: Any) -> str:
    """Render sources as readable chips grouped by type. Each chip shows a
    decoded label and keeps the raw evidence ID as a hover tooltip."""
    if not value:
        return "—"
    ids = value if isinstance(value, (list, tuple)) else [value]
    grouped: dict[str, list[str]] = {}
    order: list[str] = []
    for raw in ids:
        sid = str(raw)
        group, label = _decode_source(sid)
        if group not in grouped:
            grouped[group] = []
            order.append(group)
        chip = (
            f'<span class="src-chip" title="{html.escape(sid)}">'
            f"{html.escape(label)}</span>"
        )
        grouped[group].append(chip)
    rows = []
    for group in order:
        name = _SOURCE_GROUP_LABEL.get(group, group)
        rows.append(
            f'<div class="src-row"><span class="src-group">{html.escape(name)}</span>'
            f'<span class="src-chips">{"".join(grouped[group])}</span></div>'
        )
    return f'<div class="sources">{"".join(rows)}</div>'


def _read_analyst_packs(run_dir: Path) -> dict[str, list[dict[str, Any]]]:
    """Read optional analyst artifacts, indexed by ticker.

    Analyst packs are presentation artifacts only. Invalid optional files are
    skipped so an incomplete fallback run still produces a dashboard.
    """
    analyst_dir = run_dir / "analysts"
    views_by_ticker: dict[str, list[dict[str, Any]]] = {}
    if not analyst_dir.is_dir():
        return views_by_ticker

    for analyst_path in sorted(analyst_dir.glob("*.json")):
        try:
            payload = _read_json(analyst_path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        analyst_name = str(payload.get("analyst", analyst_path.stem))
        views = payload.get("views")
        if not isinstance(views, list):
            continue
        for view in views:
            if not isinstance(view, dict) or not view.get("ticker"):
                continue
            ticker = str(view["ticker"])
            views_by_ticker.setdefault(ticker, []).append(
                {"analyst": analyst_name, "view": view}
            )
    return views_by_ticker


def _reasoning_section(
    decision: dict[str, Any] | None, analyst_views: dict[str, list[dict[str, Any]]]
) -> str:
    """Render decision and analyst reasoning without loading market data."""
    decision = decision or {}
    has_decision = bool(decision)
    positions = decision.get("positions")
    positions = positions if isinstance(positions, dict) else {}
    weights = decision.get("weights")
    weights = weights if isinstance(weights, dict) else {}
    cards: list[str] = []

    for ticker, raw_position in positions.items():
        position = raw_position if isinstance(raw_position, dict) else {}
        ticker_text = html.escape(str(ticker))
        fields = [
            f"<li><strong>Weight:</strong> {_reasoning_text(weights.get(ticker, position.get('weight')))}</li>",
            f"<li><strong>Rationale:</strong> {_reasoning_text(position.get('rationale'))}</li>",
            f"<li><strong>Analyst weighting:</strong> {_reasoning_text(position.get('analyst_weighting'))}</li>",
            f"<li><strong>Conflicts:</strong> {_reasoning_text(position.get('conflicts'))}</li>",
            f"<li><strong>Sources:</strong> {_sources_html(position.get('sources'))}</li>",
            f"<li><strong>Confidence:</strong> {_reasoning_text(position.get('confidence'))}</li>",
            f"<li><strong>Change triggers:</strong> {_reasoning_text(position.get('change_triggers'))}</li>",
        ]
        stance_entries: list[str] = []
        for analyst_view in analyst_views.get(str(ticker), []):
            view = analyst_view["view"]
            stance_entries.append(
                "<li>"
                f"<strong>{html.escape(str(analyst_view['analyst']))}:</strong> "
                f"stance {_reasoning_text(view.get('stance'))}; "
                f"confidence {_reasoning_text(view.get('confidence'))}"
                "</li>"
            )
        stance_html = ""
        if stance_entries:
            stance_html = (
                '<p class="stance-label"><strong>Analyst stances</strong></p>'
                f"<ul>{''.join(stance_entries)}</ul>"
            )
        cards.append(
            f'<article class="reasoning-card"><h3>{ticker_text}</h3>'
            f"<ul>{''.join(fields)}</ul>{stance_html}</article>"
        )

    missing_note = ""
    if not has_decision or not analyst_views:
        missing_note = (
            '<p class="reasoning-note">No reasoning artifacts for this run '
            "(technical-only run).</p>"
        )
    thesis = ""
    regime = ""
    if has_decision:
        thesis = (
            f"<p><strong>Portfolio thesis:</strong> "
            f"{_reasoning_text(decision.get('portfolio_thesis'))}</p>"
        )
        regime = (
            f"<p><strong>Regime view:</strong> "
            f"{_reasoning_text(decision.get('regime_view'))}</p>"
        )
    positions_html = "".join(cards) or '<p class="reasoning-note">No positions in decision artifact.</p>'
    return (
        '<section class="reasoning"><h2>Reasoning</h2>'
        f"{missing_note}{thesis}{regime}{positions_html}</section>"
    )


def _render_html(
    image_data: str,
    config: dict[str, Any],
    metrics_payload: dict[str, Any],
    decision: dict[str, Any] | None,
    run_dir: Path,
    analyst_views: dict[str, list[dict[str, Any]]] | None = None,
) -> str:
    decision = decision or {}
    metrics = metrics_payload.get("metrics", metrics_payload)
    universe = config.get("universe", decision.get("universe", []))
    baselines = config.get("baselines", ["SPY", "equal_weight"])
    cutoff = decision.get("asof", metrics_payload.get("asof", config.get("asof", "unknown")))
    end = metrics_payload.get("end", config.get("end", "unknown"))
    horizon = _data_horizon(run_dir, metrics_payload, decision, str(cutoff))
    reading = _regime_reading(run_dir)
    analyst_views = analyst_views or {}
    reasoning = _reasoning_section(decision, analyst_views)
    universe_text = ", ".join(str(item) for item in universe) if universe else "not specified"
    baselines_text = ", ".join(str(item) for item in baselines)
    table = _metrics_table(metrics if isinstance(metrics, dict) else {})

    # --- hero: crash-risk reading is the one bold element ------------------- #
    pm = metrics.get("portfolio", {}) if isinstance(metrics, dict) else {}
    port_return = _format_value(pm.get("total_return"), "percent")
    port_sharpe = _format_value(pm.get("sharpe"), "number")
    port_dd = _format_value(pm.get("max_drawdown"), "percent")

    if reading:
        band = (reading.get("band") or "unknown").lower()
        color = _BAND_COLOR.get(band, "#5A6B7F")
        score = reading.get("score")
        pct = max(0.0, min(1.0, score)) * 100 if isinstance(score, (int, float)) else 0
        score_text = f"{score:.3f}" if isinstance(score, (int, float)) else "—"
        hero = f"""
<section class="hero" style="--band:{color}">
  <div class="hero-read">
    <p class="hero-kicker">Crash-risk regime at cutoff</p>
    <p class="hero-score">{html.escape(score_text)}</p>
    <p class="hero-band">{html.escape(str(reading.get('band') or 'unknown'))}</p>
  </div>
  <div class="hero-gauge" role="img"
       aria-label="Crash-risk score {html.escape(score_text)}, band {html.escape(str(reading.get('band') or 'unknown'))}">
    <div class="gauge-track"><div class="gauge-fill" style="width:{pct:.1f}%"></div></div>
    <div class="gauge-scale"><span>calm</span><span>elevated</span><span>stressed</span></div>
  </div>
</section>"""
    else:
        hero = """
<section class="hero hero-muted">
  <p class="hero-kicker">Crash-risk regime at cutoff</p>
  <p class="hero-band">not available for this run</p>
</section>"""

    kpis = f"""
<section class="kpis">
  <div class="kpi"><span class="kpi-val">{html.escape(port_return)}</span><span class="kpi-lab">Portfolio total return</span></div>
  <div class="kpi"><span class="kpi-val">{html.escape(port_sharpe)}</span><span class="kpi-lab">Sharpe ratio</span></div>
  <div class="kpi"><span class="kpi-val">{html.escape(port_dd)}</span><span class="kpi-lab">Maximum drawdown</span></div>
</section>"""

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Portfolio risk &amp; performance</title>
<style>
:root {{
  --ink: #0E1726; --paper: #F7F9FC; --slate: #5A6B7F; --line: #D8DEE7;
  --teal: #0F7B8A; --pos: #1F8A5B; --neg: #C8453B;
}}
* {{ box-sizing: border-box; }}
body {{
  font: 16px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  color: var(--ink); background: var(--paper);
  max-width: 980px; margin: 0 auto; padding: 2.5rem 1.25rem 4rem;
}}
h1 {{ font: 600 1.55rem/1.2 Georgia, "Times New Roman", serif; margin: 0 0 .25rem; letter-spacing: -.01em; }}
h2 {{ font: 600 1.15rem/1.2 Georgia, serif; margin: 2.25rem 0 .75rem; }}
h3 {{ font: 600 1rem/1.2 Georgia, serif; margin: 0 0 .5rem; }}
a {{ color: var(--teal); }}
.lede {{ color: var(--slate); margin: 0 0 1.5rem; max-width: 60ch; }}
.facts {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: .4rem 1.5rem; border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); padding: .9rem 0; margin-bottom: 1.75rem; }}
.facts div {{ font-size: .9rem; }}
.facts dt {{ color: var(--slate); font-size: .72rem; margin: 0; }}
.facts dd {{ margin: .1rem 0 0; font-weight: 500; }}
/* Hero: the one bold element. Band color drives the accent. */
.hero {{ display: grid; grid-template-columns: minmax(140px, 220px) 1fr; gap: 1.75rem; align-items: center;
  background: var(--ink); color: #EEF2F7; border-radius: 10px; padding: 1.6rem 1.9rem; }}
.hero-kicker {{ margin: 0; color: #9AA8B8; font-size: .78rem; }}
.hero-score {{ font: 700 3.4rem/1 Georgia, serif; margin: .2rem 0 0; color: var(--band, #fff); font-variant-numeric: tabular-nums; }}
.hero-band {{ margin: .25rem 0 0; font-size: 1.1rem; font-weight: 600; color: var(--band, #fff); text-transform: capitalize; }}
.hero-gauge {{ align-self: center; }}
.gauge-track {{ height: 14px; border-radius: 7px; background: linear-gradient(90deg, #1F9D6B 0%, #D98A1F 50%, #C8453B 100%); position: relative; opacity: .9; }}
.gauge-fill {{ position: absolute; top: -5px; bottom: -5px; left: 0; border-right: 3px solid #fff; }}
.gauge-scale {{ display: flex; justify-content: space-between; margin-top: .5rem; font-size: .74rem; color: #9AA8B8; }}
.hero-muted {{ grid-template-columns: 1fr; color: #9AA8B8; }}
.hero-muted .hero-band {{ color: #9AA8B8; font-weight: 500; }}
/* KPI strip */
.kpis {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 1px; background: var(--line); border: 1px solid var(--line); border-radius: 8px; overflow: hidden; margin-top: 1rem; }}
.kpi {{ background: #fff; padding: 1rem 1.1rem; display: flex; flex-direction: column; gap: .25rem; }}
.kpi-val {{ font: 600 1.5rem/1 Georgia, serif; font-variant-numeric: tabular-nums; }}
.kpi-lab {{ color: var(--slate); font-size: .8rem; }}
.curve {{ width: 100%; height: auto; border: 1px solid var(--line); border-radius: 8px; margin-top: .5rem; }}
/* Metrics table */
table.metrics {{ border-collapse: collapse; width: 100%; font-variant-numeric: tabular-nums; }}
.metrics caption {{ text-align: left; font: 600 1rem Georgia, serif; margin-bottom: .5rem; }}
.metrics th, .metrics td {{ padding: .6rem .8rem; text-align: right; border-bottom: 1px solid var(--line); }}
.metrics thead th {{ color: var(--slate); font-weight: 600; font-size: .85rem; border-bottom: 2px solid var(--ink); }}
.metrics th[scope="row"] {{ text-align: left; font-weight: 500; color: var(--ink); }}
.metrics .col-portfolio {{ background: #EEF5F6; }}
.metrics td.pos {{ color: var(--pos); }}
.metrics td.neg {{ color: var(--neg); }}
/* Reasoning */
.reasoning-card {{ border: 1px solid var(--line); border-left: 3px solid var(--teal); border-radius: 6px; padding: .85rem 1.1rem; margin-top: 1rem; background: #fff; }}
.reasoning-card ul {{ margin: .4rem 0; padding-left: 1.2rem; }}
.reasoning-card li {{ margin: .25rem 0; }}
.stance-label {{ margin: .7rem 0 .2rem; }}
.reasoning-note {{ color: var(--slate); font-style: italic; }}
/* Source chips: readable, grouped, with raw ID on hover */
.sources {{ display: flex; flex-direction: column; gap: .35rem; margin-top: .3rem; }}
.src-row {{ display: grid; grid-template-columns: 64px 1fr; gap: .6rem; align-items: start; }}
.src-group {{ font-size: .72rem; font-weight: 600; color: var(--slate); text-align: right; padding-top: .18rem; }}
.src-chips {{ display: flex; flex-wrap: wrap; gap: .3rem; }}
.src-chip {{ font: .78rem/1 "SFMono-Regular", ui-monospace, Menlo, monospace;
  background: #EEF2F6; border: 1px solid var(--line); border-radius: 5px;
  padding: .25rem .5rem; color: var(--ink); cursor: default; }}
.src-chip:hover {{ background: #E2EAF1; }}
@media (max-width: 620px) {{ .hero, .kpis {{ grid-template-columns: 1fr; }} }}
</style>
</head>
<body>
<header>
<h1>Portfolio risk &amp; performance</h1>
<p class="lede">Historical experiment scored against SPY and an equal-weight basket of the same universe. Not financial advice.</p>
<dl class="facts">
  <div><dt>Universe</dt><dd>{html.escape(universe_text)}</dd></div>
  <div><dt>Cutoff</dt><dd>{html.escape(str(cutoff))}</dd></div>
  <div><dt>Scored through</dt><dd>{html.escape(str(end))}</dd></div>
  <div><dt>Baselines</dt><dd>{html.escape(baselines_text)}</dd></div>
  <div><dt>Data horizon</dt><dd>{html.escape(horizon)}</dd></div>
</dl>
</header>
<main>
{hero}
{kpis}
<h2>Equity curve</h2>
<img class="curve" alt="Equity curve for portfolio, SPY, and equal_weight" src="data:image/png;base64,{image_data}">
<h2>Performance metrics</h2>
{table}
{reasoning}
</main>
</body>
</html>
"""


def build_dashboard(
    run_dir: str | Path, config_path: str | Path = "config.yaml", out_dir: str | Path = "app/out"
) -> dict[str, Path]:
    """Render ``run_dir`` artifacts to ``equity.png`` and ``dashboard.html``.

    Only committed run artifacts are read.  The optional ``decision.json`` is
    used for additional header context when present; its absence is supported.
    """
    run_path = Path(run_dir)
    metrics_path = run_path / "metrics.json"
    equity_path = run_path / "equity.csv"
    metrics_payload = _read_json(metrics_path)
    equity = _read_equity(equity_path)
    decision_path = run_path / "decision.json"
    decision = _read_json(decision_path) if decision_path.is_file() else None
    analyst_views = _read_analyst_packs(run_path)
    config = _parse_config(config_path)

    output = Path(out_dir)
    output.mkdir(parents=True, exist_ok=True)
    image_path = output / "equity.png"
    html_path = output / "dashboard.html"
    _plot_equity(equity, image_path)
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    page = _render_html(encoded, config, metrics_payload, decision, run_path, analyst_views)
    html_path.write_text(page, encoding="utf-8")
    return {"html": html_path, "image": image_path}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, help="run directory containing metrics.json and equity.csv")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--out-dir", default="app/out")
    args = parser.parse_args(argv)
    paths = build_dashboard(args.run, config_path=args.config, out_dir=args.out_dir)
    print(f"Wrote {paths['html']}")
    print(f"Wrote {paths['image']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
