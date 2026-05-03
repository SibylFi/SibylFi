"""
Schema-level tests for v2 changes:
  - long-only Direction
  - widened horizon_seconds (5min – 14d)
  - metadata field round-trip
  - extended Outcome enum (WIN_PARTIAL, INCONCLUSIVE, INVALID)
  - extended RiskCheck enum
"""
from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from agents.shared.signal_schema import (
    EntryCondition,
    Outcome,
    RiskAttestation,
    RiskCheck,
    Signal,
)


def _signal_kwargs(**overrides):
    base = dict(
        signal_id="0x" + "ab" * 32,
        publisher="swing.sibylfi.eth",
        token="eip155:84532/erc20:0xfff9976782d46cc05630d1f6ebab18b2324d6b14",
        direction="long",
        entry_condition=EntryCondition(reference_price=3500.0),
        target_price=3550.0,
        stop_price=3475.0,
        horizon_seconds=3600,
        confidence_bps=7000,
        published_at_block=12_345_678,
        signature="0x" + "cd" * 65,
    )
    base.update(overrides)
    return base


def test_direction_short_rejected():
    """v2 schema must reject direction='short' even though pre-v2 schemas allowed it."""
    with pytest.raises(ValidationError):
        Signal(**_signal_kwargs(direction="short"))


def test_horizon_300_accepted():
    """Lower bound of widened horizon (5 min) accepted — needed for Scalper 1m TF."""
    sig = Signal(**_signal_kwargs(horizon_seconds=300))
    assert sig.horizon_seconds == 300


def test_horizon_below_300_rejected():
    """Below the 5-minute floor must reject."""
    with pytest.raises(ValidationError):
        Signal(**_signal_kwargs(horizon_seconds=200))


def test_horizon_14d_accepted_15d_rejected():
    """Upper bound widened to 14 days for Position roadmap; 15d still out."""
    Signal(**_signal_kwargs(horizon_seconds=14 * 24 * 3600))
    with pytest.raises(ValidationError):
        Signal(**_signal_kwargs(horizon_seconds=15 * 24 * 3600))


def test_metadata_roundtrip_through_json():
    """metadata field must round-trip through model_dump_json."""
    md = {"tp1": 3525.0, "setup": "ema_stack_div_bull_pullback", "tf": "4h"}
    sig = Signal(**_signal_kwargs(metadata=md))
    serialized = sig.model_dump_json()
    parsed = json.loads(serialized)
    assert parsed["metadata"] == md
    rebuilt = Signal.model_validate_json(serialized)
    assert rebuilt.metadata == md


def test_metadata_optional_defaults_none():
    """Omitting metadata keeps backward compatibility — None default."""
    sig = Signal(**_signal_kwargs())
    assert sig.metadata is None


def test_outcome_enum_extended():
    """Three new outcome values landed on the enum."""
    assert Outcome("win_partial") is Outcome.WIN_PARTIAL
    assert Outcome("inconclusive") is Outcome.INCONCLUSIVE
    assert Outcome("invalid") is Outcome.INVALID
    # legacy values still present
    assert Outcome.WIN.value == "win"
    assert Outcome.LOSS.value == "loss"


def test_risk_check_enum_extended():
    """v2 RiskCheck values present."""
    expected_new = {
        "rr_insufficient",
        "stop_too_wide",
        "exhaustion",
        "twap_deviation",
        "stop_too_close",
        "elder_month_rule",
        "multi_tp_invalid",
        "non_long_rejected",
    }
    enum_values = {c.value for c in RiskCheck}
    assert expected_new.issubset(enum_values)


def test_risk_attestation_profile_required():
    """RiskAttestation now requires profile + appetite + numeric position metadata."""
    att = RiskAttestation(
        signal_id="0x" + "ab" * 32,
        **{"pass": True},
        failed_checks=[],
        profile="swing",
        appetite="balanced",
        position_size_usd=250.0,
        rr_ratio=2.5,
        expected_slippage_bps=15,
        pool_tvl_usd=500_000.0,
        spot_twap_deviation=0.004,
        multi_tp=True,
        risk_attester="risk.sibylfi.eth",
        signature="0x" + "cd" * 65,
    )
    assert att.profile == "swing"
    assert att.appetite == "balanced"
    assert att.multi_tp is True


def test_risk_attestation_invalid_profile_rejected():
    """profile must be one of the three Literal values."""
    with pytest.raises(ValidationError):
        RiskAttestation(
            signal_id="0x" + "ab" * 32,
            **{"pass": True},
            profile="position",  # not a v2 research profile
            appetite="balanced",
            position_size_usd=250.0,
            rr_ratio=2.5,
            expected_slippage_bps=15,
            pool_tvl_usd=500_000.0,
            spot_twap_deviation=0.004,
            risk_attester="risk.sibylfi.eth",
            signature="0x" + "cd" * 65,
        )
