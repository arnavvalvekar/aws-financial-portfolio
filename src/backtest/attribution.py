"""Portfolio return attribution helpers.

The backtest engine owns the calculation of contribution values.  This module
contains presentation-oriented helpers that operate only on the resulting
mapping, so they do not access prices or recompute a run.
"""
from __future__ import annotations

from collections.abc import Mapping


def sorted_contributions(
    contributions: Mapping[str, float],
) -> list[tuple[str, float]]:
    """Return ``(name, contribution)`` rows sorted by absolute impact.

    Sorting by absolute value puts both the largest positive contributors and
    the largest detractors first.  Python's stable sort preserves mapping order
    for ties, making display output deterministic.
    """
    return sorted(
        ((name, float(value)) for name, value in contributions.items()),
        key=lambda item: abs(item[1]),
        reverse=True,
    )


# A descriptive alias for callers that prefer the noun phrase used by the
# dashboard/CLI contract.
contribution_breakdown = sorted_contributions
