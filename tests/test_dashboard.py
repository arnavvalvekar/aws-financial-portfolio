"""Offline tests for the static dashboard shell."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from app.dashboard import build_dashboard

ROOT = Path(__file__).resolve().parents[1]


def _artifact_run(tmp_path: Path) -> Path:
    """Create a deterministic run from the committed fixture price store."""
    runs_dir = tmp_path / "runs"
    command = [
        sys.executable,
        "-m",
        "src.backtest",
        "--config",
        "tests/fixtures/config.yaml",
        "--decision",
        "tests/fixtures/decision.json",
        "--store-dir",
        "tests/fixtures/prices",
        "--runs-dir",
        str(runs_dir),
    ]
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    return runs_dir / "dev-2026-01-30"


def test_dashboard_renders_header_curve_and_metrics(tmp_path: Path):
    run_dir = _artifact_run(tmp_path)
    output = tmp_path / "app" / "out"

    paths = build_dashboard(
        run_dir,
        config_path=ROOT / "tests/fixtures/config.yaml",
        out_dir=output,
    )

    html_path = output / "dashboard.html"
    image_path = output / "equity.png"
    assert paths == {"html": html_path, "image": image_path}
    assert html_path.is_file() and html_path.stat().st_size > 0
    assert image_path.is_file() and image_path.stat().st_size > 0

    page = html_path.read_text(encoding="utf-8")
    for series in ("portfolio", "SPY", "equal_weight"):
        assert series in page
    for label in ("Total return", "CAGR", "Volatility", "Sharpe", "Max drawdown"):
        assert label in page
    for header in ("Universe:", "Cutoff (asof):", "End:", "Baselines:", "Data horizon:"):
        assert header in page
    assert "data:image/png;base64," in page


def test_dashboard_degrades_without_optional_decision(tmp_path: Path):
    source_run = _artifact_run(tmp_path / "source")
    run_without_decision = tmp_path / "without-decision"
    shutil.copytree(source_run, run_without_decision)
    decision_path = run_without_decision / "decision.json"
    if decision_path.exists():
        decision_path.unlink()

    output = tmp_path / "missing-decision" / "out"
    build_dashboard(
        run_without_decision,
        config_path=ROOT / "tests/fixtures/config.yaml",
        out_dir=output,
    )

    assert (output / "dashboard.html").is_file()
    assert (output / "dashboard.html").stat().st_size > 0
    assert (output / "equity.png").is_file()
    page = (output / "dashboard.html").read_text(encoding="utf-8")
    assert "Data horizon:" in page
    assert "portfolio" in page and "SPY" in page and "equal_weight" in page
