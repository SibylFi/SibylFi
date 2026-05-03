"""
Unit tests for the multi-tenant Research Agent registry.

DB-touching paths (CRUD, publish-signal) are exercised via the live
docker-compose orchestrator in scripts/test_custom_agents_e2e.sh.
This module covers the pure helpers.
"""
from __future__ import annotations

import pytest

from agents.shared.strategies.snapshot import ScalperParams, SwingParams
from orchestrator.custom_agents import (
    _hydrate_params,
    _persona_from_row,
    serialize_default_params,
)


def test_hydrate_swing_params_default():
    p = _hydrate_params("swing", {})
    assert isinstance(p, SwingParams)
    assert p.min_dow_bars == 15
    assert p.confidence_cap == 9000


def test_hydrate_swing_params_partial_override():
    p = _hydrate_params("swing", {"min_dow_bars": 25, "sl_pct": 0.01})
    assert p.min_dow_bars == 25
    assert p.sl_pct == 0.01
    assert p.confidence_cap == 9000   # untouched


def test_hydrate_ignores_unknown_keys():
    """Unknown JSON keys should be silently dropped, not raise."""
    p = _hydrate_params("swing", {"min_dow_bars": 20, "rocket_fuel": True})
    assert p.min_dow_bars == 20


def test_hydrate_scalper_default():
    p = _hydrate_params("scalper", {})
    assert isinstance(p, ScalperParams)
    assert p.confidence_cap == 8500
    assert p.mode == "Balanced"


def test_hydrate_scalper_mode_override():
    p = _hydrate_params("scalper", {"mode": "Discovery"})
    assert p.mode == "Discovery"


def test_default_params_swing_serializable():
    raw = serialize_default_params("swing")
    assert raw["min_dow_bars"] == 15
    assert raw["confidence_cap"] == 9000
    # Must be plain JSON-serializable types
    import json
    json.dumps(raw)


def test_default_params_scalper_serializable():
    raw = serialize_default_params("scalper")
    assert raw["mode"] == "Balanced"
    assert raw["confidence_cap"] == 8500
    import json
    json.dumps(raw)


def test_persona_from_row_swing_roundtrip():
    row = {
        "id": 1,
        "ens_name": "alpha-one.sibyl.eth",
        "display_name": "Alpha One",
        "profile": "swing",
        "appetite": "balanced",
        "token": "WETH/USDC",
        "price_per_signal_usdc": 1.50,
        "params_json": {"min_dow_bars": 18},
        "owner_address": "0xabc",
        "private_key": "0x" + "11" * 32,
        "created_at": None,
    }
    persona = _persona_from_row(row)
    assert persona.profile == "swing"
    assert persona.ens_name == "alpha-one.sibyl.eth"
    assert persona.swing_params is not None
    assert persona.swing_params.min_dow_bars == 18
    assert persona.scalper_params is None


def test_persona_from_row_scalper_roundtrip():
    row = {
        "id": 2,
        "ens_name": "fast-fox.sibyl.eth",
        "display_name": "Fast Fox",
        "profile": "scalper",
        "appetite": "aggressive",
        "token": "WBTC/USDC",
        "price_per_signal_usdc": 0.25,
        "params_json": {"mode": "Discovery", "tp_rr": 2.5},
        "owner_address": "0xdef",
        "private_key": "0x" + "22" * 32,
        "created_at": None,
    }
    persona = _persona_from_row(row)
    assert persona.profile == "scalper"
    assert persona.scalper_params is not None
    assert persona.scalper_params.mode == "Discovery"
    assert persona.scalper_params.tp_rr == 2.5
    assert persona.swing_params is None


if __name__ == "__main__":
    import sys
    pytest.main([__file__, "-q", "--tb=short"])
