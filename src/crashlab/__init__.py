"""CrashLab: stress-test the frozen portfolio against crisis scenarios.

A what-if layer on top of the already-frozen decision.json. It never changes the
scored decision; it re-prices the same weights under shock scenarios and reports
how they would have held up, then proposes protective changes with trade-offs.

Point-in-time note: CrashLab only shocks weights that are already frozen, so it
is allowed to look at any window (exactly like the backtest's post-cutoff
scoring). It reuses Person A's backtest engine and metrics and Person B's LLM
wrapper; it does not modify them.

Owner: C (this stretch feature), building on A's pricing and B's agent pattern.
"""
