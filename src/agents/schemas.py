"""Tool-call JSON schemas for analyst views and the portfolio manager decision. See SCHEMAS.md."""

ANALYSTS = ["technical", "fundamentals", "macro", "sentiment", "geopolitics"]

_STRINGS = {"type": "array", "items": {"type": "string"}}


def analyst_schema(universe):
    view = {
        "type": "object",
        "properties": {
            "ticker": {"type": "string", "enum": list(universe)},
            "stance": {"type": "number", "description": "-1 strong underweight to +1 strong overweight"},
            "confidence": {"type": "number", "description": "0 to 1"},
            "thesis": {"type": "string"},
            "evidence": _STRINGS,
            "change_triggers": _STRINGS,
        },
        "required": ["ticker", "stance", "confidence", "thesis", "evidence", "change_triggers"],
    }
    return {
        "type": "object",
        "properties": {"views": {"type": "array", "items": view}},
        "required": ["views"],
    }


def pm_schema(universe, analysts):
    ids = list(universe) + ["CASH"]
    position = {
        "type": "object",
        "properties": {
            "rationale": {"type": "string"},
            "analyst_weighting": {
                "type": "object",
                "properties": {a: {"type": "number"} for a in analysts},
                "required": list(analysts),
            },
            "conflicts": _STRINGS,
            "sources": _STRINGS,
            "confidence": {"type": "number"},
            "change_triggers": _STRINGS,
        },
        "required": ["rationale", "analyst_weighting", "conflicts", "sources", "confidence", "change_triggers"],
    }
    return {
        "type": "object",
        "properties": {
            "weights": {
                "type": "object",
                "properties": {t: {"type": "number"} for t in ids},
                "required": ids,
            },
            "positions": {
                "type": "object",
                "properties": {t: position for t in universe},
                "required": list(universe),
            },
            "portfolio_thesis": {"type": "string"},
            "regime_view": {"type": "string"},
        },
        "required": ["weights", "positions", "portfolio_thesis", "regime_view"],
    }
