"""Evidence modules for Person A's data lane.

Each module builds a point-in-time evidence pack (contract C4 / SCHEMAS.md) for
one analyst. All price data is read exclusively through ``src.pit`` so the
no-look-ahead guard is enforced in one place.
"""
