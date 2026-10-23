"""Shared pytest fixtures for Person A's data/backtest lane (T2 / contract C6).

Provides a committed, offline fixture price store plus a sample decision and a
copy of the project config, so the pit / evidence / backtest tests (T3, T4, T6,
T7) run deterministically WITHOUT hitting the network.

Exposed fixtures:
  - fixture_store_dir : Path to tests/fixtures/prices (C1/C2-schema CSVs)
  - sample_decision   : parsed dict from tests/fixtures/decision.json
  - sample_config     : parsed dict from tests/fixtures/config.yaml

Also installs the `sys.path` shim so `import src.*` works without installing
the package (mirrors tests/test_prices_source.py).

Fixture store: AAPL, MSFT, KO, NVDA + SPY, a frozen real Yahoo snapshot
(2024-10-23 .. 2026-10-16, 497 rows each, shared date index). AAPL and every
other ticker carry 318 trading rows on or before the 2026-01-30 cutoff, so the
200-day trend signal is testable fully offline.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# --- import shim: make `src` importable without installing the package ------
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _parse_config(path: Path) -> dict:
    """Parse the config YAML.

    Uses PyYAML when present. The project venv pins only pandas/pytest/requests
    (no YAML lib), so fall back to a minimal parser that handles this flat
    config's shape: scalars, one nested mapping (`constraints`), inline list
    literals, and `# comments`. Kept deliberately small and local to the test
    layer — it is not a general YAML implementation.
    """
    try:
        import yaml  # type: ignore
    except ModuleNotFoundError:
        return _parse_config_minimal(path)
    with path.open() as fh:
        return yaml.safe_load(fh)


def _coerce(raw: str):
    s = raw.strip()
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        if not inner:
            return []
        return [_coerce(x) for x in inner.split(",")]
    if s.lower() in ("true", "false"):
        return s.lower() == "true"
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s.strip("'\"")


def _strip_comment(line: str) -> str:
    # Remove a trailing ` # comment`. Safe here: no '#' appears inside values.
    if "#" in line:
        line = line.split("#", 1)[0]
    return line.rstrip()


def _parse_config_minimal(path: Path) -> dict:
    result: dict = {}
    current_map: dict | None = None
    with path.open() as fh:
        for raw_line in fh:
            line = _strip_comment(raw_line)
            if not line.strip():
                continue
            indented = line[0] in (" ", "\t")
            key, _, value = line.strip().partition(":")
            key = key.strip()
            value = value.strip()
            if indented and current_map is not None:
                current_map[key] = _coerce(value)
                continue
            if value == "":
                # Start of a nested mapping (e.g. `constraints:`).
                current_map = {}
                result[key] = current_map
            else:
                result[key] = _coerce(value)
                current_map = None
    return result


@pytest.fixture(scope="session")
def fixture_store_dir() -> Path:
    """Path to the committed offline price store (C1/C2-schema CSVs)."""
    d = FIXTURES / "prices"
    assert d.is_dir(), f"fixture price store missing: {d}"
    return d


@pytest.fixture(scope="session")
def sample_decision() -> dict:
    """Parsed sample decision.json (valid weights: caps + sum == 1.0)."""
    with (FIXTURES / "decision.json").open() as fh:
        return json.load(fh)


@pytest.fixture(scope="session")
def sample_config() -> dict:
    """Parsed copy of the project config.yaml."""
    return _parse_config(FIXTURES / "config.yaml")
