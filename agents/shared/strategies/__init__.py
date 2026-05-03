"""Pure-Python ports of the indicator math used by the v2 Research Agents.

The Pine scripts in /agents/*.pine are the source of truth for behavior;
this package re-implements the subset of TradingView's `ta.*` family that
the swing and scalper strategies need.

NEVER add a third-party TA dependency — the deterministic mock-replay path
depends on having no opaque external behavior.
"""
