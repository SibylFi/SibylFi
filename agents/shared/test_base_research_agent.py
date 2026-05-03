"""
End-to-end tests for the v2 BaseResearchAgent.

Coverage:
  • Strategy reject path → generate_signal returns None.
  • Strategy accept path → returns a signed Signal with strategy-derived
    levels and metadata, profile stamped, direction == "long".
  • LLM calibrator delta is applied within [base, cap].
  • CONFIDENCE_DELTA parser is bounded to ±1000 even if LLM emits more.
"""
from __future__ import annotations

import asyncio
import dataclasses

import pytest

from agents.shared.base_research_agent import (
    BaseResearchAgent,
    PersonaConfig,
    _parse_calibration,
)
from agents.shared.signal_schema import Signal
from agents.shared.strategies.snapshot import (
    ScalperFeatures,
    SwingFeatures,
    SwingParams,
)


_DUMMY_KEY = "0x" + "11" * 32


def _persona(profile: str) -> PersonaConfig:
    return PersonaConfig(
        name=profile,
        profile=profile,
        ens_name=f"{profile}.sibylfi.eth",
        private_key=_DUMMY_KEY,
        price_per_signal_usdc=0.5,
        prompt_template="t={token} p={profile} s={setup} c={confidence_base}/{confidence_cap} "
                       "ref={reference_price} tp={target_price} sl={stop_price} h={horizon_seconds}",
    )


def _patch_persist(agent: BaseResearchAgent) -> None:
    async def _noop(_signal):
        return None
    agent._persist = _noop  # type: ignore[assignment]


def _patch_features(monkeypatch, features) -> None:
    """Force load_features to return a known fixture regardless of token."""
    monkeypatch.setattr(
        "agents.shared.base_research_agent.load_features",
        lambda profile, token: features,
    )


# ─── Calibrator parser ──────────────────────────────────────────────────


def test_parse_calibration_basic():
    delta, thesis = _parse_calibration(
        "CONFIDENCE_DELTA: +250\nTHESIS: Trend confirmed across all anchors."
    )
    assert delta == 250
    assert thesis == "Trend confirmed across all anchors."


def test_parse_calibration_clamps_at_plus_minus_1000():
    delta, _ = _parse_calibration("CONFIDENCE_DELTA: +9999\nTHESIS: x")
    assert delta == 1000
    delta, _ = _parse_calibration("CONFIDENCE_DELTA: -9999\nTHESIS: x")
    assert delta == -1000


def test_parse_calibration_missing_fields_default_safely():
    delta, thesis = _parse_calibration("garbage with no delta or thesis")
    assert delta == 0
    assert thesis == "Calibration unavailable."


def test_parse_calibration_negative_zero():
    delta, _ = _parse_calibration("CONFIDENCE_DELTA: -0\nTHESIS: ok")
    assert delta == 0


# ─── Generate signal — strategy reject path ─────────────────────────────


def test_generate_signal_returns_none_when_strategy_rejects(monkeypatch):
    """If swing strategy rejects (e.g. EMA stack not bullish), agent returns None."""
    bad = SwingFeatures(
        token="WETH/USDC", tf="4h",
        spot_price=3450.0, twap_30m=3450.0,
        open_=3440.0, high=3460.0, low=3430.0, close=3450.0,
        volume=1500.0, avg_volume_20=1200.0,
        ema10=3445.0, ema55=3400.0, ema100=3300.0, ema200=3000.0,
        rsi_14=55.0, atr_14=30.0, pivot_R3=3600.0,
        ema_stack_bull=False,                   # ← rejection trigger
        price_above_ema200=True,
        dow_bull_bars=22,
        bull_div_regular=True, bull_div_hidden=False,
        bear_div_regular=False, bear_div_hidden=False,
        pullback_to_ema10=True, bull_candle=True, volume_ok=True,
    )
    _patch_features(monkeypatch, bad)

    agent = BaseResearchAgent(_persona("swing"))
    _patch_persist(agent)

    out = asyncio.get_event_loop().run_until_complete(
        agent.generate_signal(token="WETH/USDC", published_at_block=1)
    )
    assert out is None


# ─── Generate signal — happy path (swing) ───────────────────────────────


def _swing_perfect() -> SwingFeatures:
    return SwingFeatures(
        token="WETH/USDC", tf="4h",
        spot_price=3450.0, twap_30m=3450.0,
        open_=3440.0, high=3460.0, low=3430.0, close=3450.0,
        volume=1500.0, avg_volume_20=1200.0,
        ema10=3445.0, ema55=3400.0, ema100=3300.0, ema200=3000.0,
        rsi_14=58.0, atr_14=30.0, pivot_R3=3600.0,
        ema_stack_bull=True, price_above_ema200=True,
        dow_bull_bars=22,
        bull_div_regular=True, bull_div_hidden=False,
        bear_div_regular=False, bear_div_hidden=False,
        pullback_to_ema10=True, bull_candle=True, volume_ok=True,
    )


def test_generate_signal_swing_happy_path(monkeypatch):
    _patch_features(monkeypatch, _swing_perfect())

    agent = BaseResearchAgent(_persona("swing"))
    _patch_persist(agent)

    sig = asyncio.get_event_loop().run_until_complete(
        agent.generate_signal(token="WETH/USDC", published_at_block=12345)
    )
    assert isinstance(sig, Signal)
    assert sig.direction == "long"
    assert sig.publisher == "swing.sibylfi.eth"
    assert sig.entry_condition.reference_price == 3450.0

    # base 8000 from strategy + LLM delta in [-300, +300] → final ∈ [7700, 8300]
    assert 7700 <= sig.confidence_bps <= 8300

    # Strategy metadata + agent metadata both present
    assert sig.metadata["profile"] == "swing"
    assert sig.metadata["rr_structure"] == "2:1 / 3:1 multi-TP"
    assert sig.metadata["dow_bull_bars"] == 22
    assert "tp1" in sig.metadata
    assert "thesis" in sig.metadata and len(sig.metadata["thesis"]) > 0

    # Stop is exactly entry × 0.995 in v2 swing (Elder 0.5% SL)
    assert sig.stop_price == round(3450.0 * 0.995, 6)


def test_generate_signal_confidence_capped_at_strategy_cap(monkeypatch):
    """Even if LLM tries to push past 9000, the strategy cap binds."""
    f = _swing_perfect()
    _patch_features(monkeypatch, f)

    # Force base near cap so any positive delta would clear 9000
    persona = dataclasses.replace(
        _persona("swing"),
        swing_params=SwingParams(
            confidence_base=8950, div_regular_bonus=0, dow_long_bonus=0,
            confidence_cap=9000,
        ),
    )
    agent = BaseResearchAgent(persona)
    _patch_persist(agent)

    sig = asyncio.get_event_loop().run_until_complete(
        agent.generate_signal(token="WETH/USDC", published_at_block=1)
    )
    assert sig is not None
    assert sig.confidence_bps <= 9000
    # Lower bound: base 8950 minus max mock delta 300 = 8650
    assert sig.confidence_bps >= 8650


# ─── Generate signal — happy path (scalper) ─────────────────────────────


def _scalper_perfect() -> ScalperFeatures:
    return ScalperFeatures(
        token="WETH/USDC", tf="5m",
        spot_price=3450.0, twap_30m=3450.0,
        close=3450.0, atr_pct=0.45,
        spring_signal=False, pullback_signal=True,
        bounce_signal=False, breakout_signal=False,
        has_structure=True, is_ranging=False, is_bullish=True,
        btc_change_20b=0.5, bullish_consensus=3,
        relative_strength=0.4, use_rel_strength=False,
        setup_weights={"Spring": 0.5, "Pullback": 0.7, "Bounce": 0.5, "Breakout": 0.5},
        consec_losses=0, daily_pnl_pct=0.5, in_cooldown=False,
    )


def test_generate_signal_scalper_happy_path(monkeypatch):
    _patch_features(monkeypatch, _scalper_perfect())

    agent = BaseResearchAgent(_persona("scalper"))
    _patch_persist(agent)

    sig = asyncio.get_event_loop().run_until_complete(
        agent.generate_signal(token="WETH/USDC", published_at_block=42)
    )
    assert sig is not None
    assert sig.direction == "long"
    assert sig.publisher == "scalper.sibylfi.eth"
    assert sig.metadata["profile"] == "scalper"
    assert sig.metadata["setup"] == "Pullback"
    assert sig.metadata["rr_structure"] == "2:1 single TP"
    # Pullback base 7000 ± 300 mock delta, scalper cap 8500
    assert 6700 <= sig.confidence_bps <= 7300
    assert sig.horizon_seconds == 3600


if __name__ == "__main__":
    import sys
    pytest.main([__file__, "-q", "--tb=short"])
