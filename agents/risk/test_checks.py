"""
Risk Agent v2 — profile-aware deterministic check tests.

Covers the 8+ scenarios called out in the migration plan §1.2:
  1. swing-balanced passes a clean swing signal
  2. swing-conservative tightens RR floor
  3. scalper-aggressive accepts wider slippage than scalper-balanced
  4. scalper rejects horizon that auto-classifies into swing (profile detection)
  5. swing rejects when metadata.tp1 is above target_price (MULTI_TP_INVALID)
  6. intraday auto-selected for horizon_seconds=43200
  7. self-purchase rejected (buyer == publisher)
  8. non-long rejected at the Risk Agent layer (defense-in-depth)
"""
from __future__ import annotations

import os

import pytest

# Provide a deterministic key for sign_risk_attestation
os.environ.setdefault("RISK_KEY", "0x" + "11" * 32)

from agents.risk.checks import PoolMetrics, RiskChecker, _detect_profile  # noqa: E402
from agents.shared.signal_schema import EntryCondition, RiskCheck, Signal  # noqa: E402


_PRIV = os.environ["RISK_KEY"]
_PUBLISHER = "0x1111111111111111111111111111111111111111"
_BUYER = "0x2222222222222222222222222222222222222222"


def _mk_signal(
    *,
    direction: str = "long",
    horizon_seconds: int = 86400,
    ref: float = 3500.0,
    target: float = 3565.0,
    stop: float = 3475.0,
    metadata: dict | None = None,
) -> Signal:
    sig = Signal(
        signal_id="0x" + "ab" * 32,
        publisher="swing.sibylfi.eth",
        token="eip155:84532/erc20:0xfff9976782d46cc05630d1f6ebab18b2324d6b14",
        direction="long",  # always long via schema; mutate after if needed
        entry_condition=EntryCondition(reference_price=ref),
        target_price=target,
        stop_price=stop,
        horizon_seconds=horizon_seconds,
        confidence_bps=8000,
        published_at_block=12_345_678,
        metadata=metadata,
        signature="0x" + "cd" * 65,
    )
    if direction != "long":
        # bypass schema — defense-in-depth test
        object.__setattr__(sig, "direction", direction)
    return sig


def _mk_pool(ref: float = 3500.0, slippage_bps: int = 8, tvl: float = 2_500_000.0) -> PoolMetrics:
    return PoolMetrics(
        tvl_usd=tvl,
        expected_slippage_bps_at_size=slippage_bps,
        atr_24h=0.012,
        atr_30d_avg=0.010,
        exhaustion_cost=tvl * 0.5,
        spot_price=ref,
        twap_30m=ref,
    )


@pytest.fixture
def checker() -> RiskChecker:
    return RiskChecker(priv_key=_PRIV)


# 1. swing-balanced passes a clean swing signal
def test_swing_balanced_passes_clean(checker):
    sig = _mk_signal(horizon_seconds=86400, ref=3500.0, target=3565.0, stop=3475.0)  # rr=2.6
    att = checker.check(
        signal=sig, capital_usd=50_000, pool=_mk_pool(),
        buyer_addr=_BUYER, publisher_addr=_PUBLISHER, appetite="balanced",
    )
    assert att.pass_, f"expected pass, failed_checks={att.failed_checks}"
    assert att.profile == "swing"
    assert att.appetite == "balanced"
    assert att.rr_ratio == pytest.approx(2.6, abs=0.01)


# 2. swing-conservative tightens RR floor: rr=2.6 passes balanced (>=2.5) but fails conservative (>=3.0)
def test_swing_conservative_tightens_rr(checker):
    sig = _mk_signal(horizon_seconds=86400, ref=3500.0, target=3565.0, stop=3475.0)
    att = checker.check(
        signal=sig, capital_usd=50_000, pool=_mk_pool(),
        buyer_addr=_BUYER, publisher_addr=_PUBLISHER, appetite="conservative",
    )
    assert not att.pass_
    assert RiskCheck.RR_INSUFFICIENT in att.failed_checks


# 3. scalper-aggressive accepts wider slippage than scalper-balanced
def test_scalper_aggressive_accepts_wider_slippage(checker):
    # scalper-balanced max_slippage_bps = 80; aggressive = 110
    sig = _mk_signal(horizon_seconds=1800, ref=3500.0, target=3535.0, stop=3482.5)  # rr=2.0, stop=0.5%
    pool_high_slip = _mk_pool(slippage_bps=100)

    bal = checker.check(
        signal=sig, capital_usd=50_000, pool=pool_high_slip,
        buyer_addr=_BUYER, publisher_addr=_PUBLISHER, appetite="balanced",
    )
    agg = checker.check(
        signal=sig, capital_usd=50_000, pool=pool_high_slip,
        buyer_addr=_BUYER, publisher_addr=_PUBLISHER, appetite="aggressive",
    )
    assert RiskCheck.SLIPPAGE in bal.failed_checks
    assert RiskCheck.SLIPPAGE not in agg.failed_checks


# 4. profile auto-detection: horizon=86400 → swing, horizon=1800 → scalper
def test_profile_auto_detection_boundaries(checker):
    sig_swing = _mk_signal(horizon_seconds=86400)
    sig_scalper = _mk_signal(horizon_seconds=1800, ref=3500.0, target=3535.0, stop=3482.5)
    sig_intraday = _mk_signal(horizon_seconds=43200, ref=3500.0, target=3535.0, stop=3482.5)
    assert _detect_profile(sig_swing) == "swing"
    assert _detect_profile(sig_scalper) == "scalper"
    assert _detect_profile(sig_intraday) == "intraday"


# 5. swing rejects when metadata.tp1 is above target_price (MULTI_TP_INVALID)
def test_swing_multi_tp_invalid(checker):
    sig = _mk_signal(
        horizon_seconds=86400, ref=3500.0, target=3565.0, stop=3475.0,
        metadata={"tp1": 3600.0},  # tp1 > target — invalid
    )
    att = checker.check(
        signal=sig, capital_usd=50_000, pool=_mk_pool(),
        buyer_addr=_BUYER, publisher_addr=_PUBLISHER, appetite="balanced",
    )
    assert not att.pass_
    assert RiskCheck.MULTI_TP_INVALID in att.failed_checks


# 6. intraday auto-selected for horizon_seconds=43200 (12h)
def test_intraday_auto_selected(checker):
    sig = _mk_signal(horizon_seconds=43200, ref=3500.0, target=3535.0, stop=3482.5)
    att = checker.check(
        signal=sig, capital_usd=50_000, pool=_mk_pool(),
        buyer_addr=_BUYER, publisher_addr=_PUBLISHER, appetite="balanced",
    )
    assert att.profile == "intraday"


# 7. self-purchase rejected
def test_self_purchase_rejected(checker):
    sig = _mk_signal(horizon_seconds=86400, ref=3500.0, target=3565.0, stop=3475.0)
    att = checker.check(
        signal=sig, capital_usd=50_000, pool=_mk_pool(),
        buyer_addr=_PUBLISHER, publisher_addr=_PUBLISHER,
        appetite="balanced",
    )
    assert not att.pass_
    assert RiskCheck.SELF_PURCHASE in att.failed_checks


# 8. non-long rejected at Risk Agent layer (defense-in-depth)
def test_non_long_rejected_defense_in_depth(checker):
    sig = _mk_signal(horizon_seconds=86400, ref=3500.0, target=3565.0, stop=3475.0)
    object.__setattr__(sig, "direction", "short")
    att = checker.check(
        signal=sig, capital_usd=50_000, pool=_mk_pool(),
        buyer_addr=_BUYER, publisher_addr=_PUBLISHER, appetite="balanced",
    )
    assert not att.pass_
    assert RiskCheck.NON_LONG_REJECTED in att.failed_checks


# Bonus: balanced has zero uplifts (identity check)
def test_balanced_appetite_is_identity(checker):
    """Balanced appetite must be the no-op identity for uplift fields (per plan §1.2)."""
    appetites = checker._appetites["balanced"]
    assert appetites["min_rr_uplift_above_floor"] == 0
    assert appetites["max_position_pct_capital_uplift"] == 0
    assert appetites["max_slippage_bps_uplift_below_floor"] == 0
    assert appetites["min_pool_tvl_uplift_usd"] == 0
