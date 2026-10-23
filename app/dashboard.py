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
    figure, axis = plt.subplots(figsize=(10, 5.5), constrained_layout=True)
    for name in SERIES:
        axis.plot(equity.index, equity[name], linewidth=2, label=name)
    axis.set_title("Portfolio equity curve")
    axis.set_xlabel("Date")
    axis.set_ylabel("Growth of $1")
    axis.grid(True, alpha=0.25)
    axis.legend()
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
            cells.append(f"<td>{html.escape(_format_value(value, kind))}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    headers = "".join(f"<th scope=\"col\">{html.escape(name)}</th>" for name in SERIES)
    return (
        '<table class="metrics"><caption>Performance metrics</caption>'
        f"<thead><tr><th scope=\"col\">Metric</th>{headers}</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def _regime_summary(run_dir: Path) -> str | None:
    """Read the crash-risk / regime pack (if committed beside the run) and return
    a short 'score (band)' string for the header. Artifact-only: reads
    run_dir/evidence/regime.json, never recomputes. Returns None if absent."""
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
            score = token.split("=", 1)[1]
        elif token.startswith("band="):
            band = token.split("=", 1)[1]
    if score is None and band is None:
        return None
    parts = []
    if score is not None:
        parts.append(f"score {score}")
    if band is not None:
        parts.append(f"band {band}")
    return " · ".join(parts)


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
            f"<li><strong>Sources:</strong> {_reasoning_text(position.get('sources'))}</li>",
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
    regime = _regime_summary(run_dir)
    analyst_views = analyst_views or {}
    reasoning = _reasoning_section(decision, analyst_views)
    universe_text = ", ".join(str(item) for item in universe) if universe else "not specified"
    baselines_text = ", ".join(str(item) for item in baselines)
    table = _metrics_table(metrics if isinstance(metrics, dict) else {})
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Financial portfolio dashboard</title>
<style>
body {{ font: 16px system-ui, sans-serif; max-width: 1100px; margin: 2rem auto; padding: 0 1rem; color: #17202a; }}
header {{ border: 1px solid #c8d1dc; border-radius: .5rem; padding: 1rem 1.25rem; background: #f5f8fb; }}
header p {{ margin: .35rem 0; }}
.curve {{ width: 100%; height: auto; border: 1px solid #d6dce3; margin-top: 1.25rem; }}
table {{ border-collapse: collapse; width: 100%; margin-top: 1.25rem; }}
th, td {{ border-bottom: 1px solid #d6dce3; padding: .55rem .7rem; text-align: right; }}
th:first-child, td:first-child {{ text-align: left; }}
caption {{ font-size: 1.2rem; font-weight: 650; text-align: left; margin-bottom: .5rem; }}
.reasoning {{ margin-top: 1.75rem; }}
.reasoning-card {{ border: 1px solid #d6dce3; border-radius: .5rem; padding: .8rem 1rem; margin-top: 1rem; background: #fbfcfd; }}
.reasoning-card h3 {{ margin: 0 0 .4rem; }}
.reasoning-card ul {{ margin: .35rem 0; padding-left: 1.25rem; }}
.reasoning-card li {{ margin: .25rem 0; }}
.stance-label {{ margin: .75rem 0 .25rem; }}
.reasoning-note {{ color: #536273; font-style: italic; }}
</style>
</head>
<body>
<header>
<h1>Financial portfolio dashboard</h1>
<p><strong>Universe:</strong> {html.escape(universe_text)}</p>
<p><strong>Cutoff (asof):</strong> {html.escape(str(cutoff))}</p>
<p><strong>End:</strong> {html.escape(str(end))}</p>
<p><strong>Baselines:</strong> {html.escape(baselines_text)}</p>
<p><strong>Data horizon:</strong> {html.escape(horizon)}</p>
{(f'<p><strong>Crash-risk (regime):</strong> {html.escape(regime)}</p>' if regime else '')}
</header>
<main>
<h2>Equity curve</h2>
<p>Series: <strong>portfolio</strong>, <strong>SPY</strong>, <strong>equal_weight</strong></p>
<img class="curve" alt="Equity curve for portfolio, SPY, and equal_weight" src="data:image/png;base64,{image_data}">
{reasoning}
{table}
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
