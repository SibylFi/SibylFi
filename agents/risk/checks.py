"""
Risk Agent — profile-aware deterministic checks against a Signal.

v2 changes:
  - Profile auto-detected from signal.horizon_seconds (swing/scalper/intraday).
  - Risk appetite layer (conservative/balanced/aggressive) applied on top of
    the profile floor — see _effective_thresholds() for combination rules.
  - 11 ordered checks; first match short-circuits (we still walk all of them
    to populate failed_checks for diagnostic clarity).
  - Defense-in-depth NON_LONG_REJECTED check even though the schema bans short.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import structlog

from agents.shared.signal_schema import RiskAttestation, RiskCheck, Signal
from agents.shared.signing import sign_risk_attestation

log = structlog.get_logger(__name__)

Profile = Literal["swing", "scalper", "intraday"]
Appetite = Literal["conservative", "balanced", "aggressive"]


@dataclass
class PoolMetrics:
    """What we'd query from Uniswap V3 for the signal's token pair."""
    tvl_usd: float
    expected_slippage_bps_at_size: int
    atr_24h: float
    atr_30d_avg: float
    exhaustion_cost: float = 0.0   # in USD; mocks set to tvl_usd * 0.5
    spot_price: float = 0.0
    twap_30m: float = 0.0


def _detect_profile(signal: Signal) -> Profile:
    """Auto-detect profile from horizon. Per agent-risk.md §2."""
    if signal.horizon_seconds <= 7200:
        return "scalper"
    if signal.horizon_seconds >= 86400:
        return "swing"
    return "intraday"


def _effective_thresholds(profile_floor: dict, appetite_uplift: dict) -> dict:
    """
    Combine profile floor with risk-appetite uplift per the rules in the
    migration plan §1.2:
      min_rr:                    profile + appetite delta (additive)
      max_position_pct_capital:  min(profile, profile + appetite delta) — appetite cannot relax
      max_slippage_bps:          profile + appetite delta (additive; negative uplift tightens)
      min_pool_tvl_usd:          profile + appetite delta (additive)
      max_stop_pct:              profile-only (appetite cannot relax)
      max_spot_twap_dev:         profile-only (appetite cannot relax)
      min_confidence_bps:        appetite-only
    """
    p = profile_floor
    a = appetite_uplift
    pos_cap = p["max_position_pct_capital"] + a["max_position_pct_capital_uplift"]
    return {
        "min_rr": p["min_rr"] + a["min_rr_uplift_above_floor"],
        "max_position_pct_capital": min(p["max_position_pct_capital"], pos_cap),
        "max_slippage_bps": p["max_slippage_bps"] + a["max_slippage_bps_uplift_below_floor"],
        "min_pool_tvl_usd": p["min_pool_tvl_usd"] + a["min_pool_tvl_uplift_usd"],
        "max_stop_pct": p["max_stop_pct"],
        "max_spot_twap_dev": p["max_spot_twap_dev"],
        "min_confidence_bps": a["min_confidence_bps"],
        "max_horizon_seconds": p["max_horizon_seconds"],
        "min_horizon_seconds": p["min_horizon_seconds"],
    }


class RiskChecker:
    def __init__(self, priv_key: str, attester_ens: str = "risk.sibylfi.eth"):
        self.priv_key = priv_key
        self.attester_ens = attester_ens
        here = Path(__file__).resolve().parent
        self._thresholds = json.loads((here / "thresholds.json").read_text())
        self._appetites = json.loads((here / "risk_appetites.json").read_text())

    def check(
        self,
        signal: Signal,
        capital_usd: float,
        pool: PoolMetrics,
        buyer_addr: str,
        publisher_addr: str,
        appetite: Appetite = "balanced",
    ) -> RiskAttestation:
        failed: list[RiskCheck] = []
        profile: Profile = _detect_profile(signal)

        thresholds = _effective_thresholds(
            self._thresholds[profile],
            self._appetites[appetite],
        )
        glob = self._thresholds["global"]

        # Position sizing per Elder 1% rule
        ref_price = signal.entry_condition.reference_price
        risk_per_unit = abs(ref_price - signal.stop_price)
        if risk_per_unit > 0:
            position_units = (capital_usd * glob["elder_risk_pct_per_trade"]) / risk_per_unit
            position_size_usd = min(position_units * ref_price, glob["max_position_size_usd_cap"])
        else:
            position_size_usd = 0.0

        reward = abs(signal.target_price - ref_price)
        rr = (reward / risk_per_unit) if risk_per_unit > 0 else 0.0
        stop_pct = (risk_per_unit / ref_price) if ref_price > 0 else 1.0
        spot_twap_dev = (
            abs(pool.spot_price - pool.twap_30m) / pool.twap_30m
            if pool.twap_30m > 0
            else 0.0
        )
        multi_tp = bool(signal.metadata and signal.metadata.get("tp1") is not None)

        # 1. NON_LONG defense-in-depth (schema already blocks)
        if signal.direction != "long":
            failed.append(RiskCheck.NON_LONG_REJECTED)

        # 2. POSITION_SIZE
        if position_size_usd > capital_usd * thresholds["max_position_pct_capital"]:
            failed.append(RiskCheck.POSITION_SIZE)

        # 3. RR_INSUFFICIENT
        if rr < thresholds["min_rr"]:
            failed.append(RiskCheck.RR_INSUFFICIENT)

        # 4. STOP_TOO_WIDE
        if stop_pct > thresholds["max_stop_pct"]:
            failed.append(RiskCheck.STOP_TOO_WIDE)

        # 5. SLIPPAGE
        if pool.expected_slippage_bps_at_size > thresholds["max_slippage_bps"]:
            failed.append(RiskCheck.SLIPPAGE)

        # 6. LIQUIDITY
        if pool.tvl_usd < thresholds["min_pool_tvl_usd"]:
            failed.append(RiskCheck.LIQUIDITY)

        # 7. EXHAUSTION
        if pool.exhaustion_cost > 0 and position_size_usd > pool.exhaustion_cost * glob["exhaustion_cost_max_position_ratio"]:
            failed.append(RiskCheck.EXHAUSTION)

        # 8. TWAP_DEVIATION
        if spot_twap_dev > thresholds["max_spot_twap_dev"]:
            failed.append(RiskCheck.TWAP_DEVIATION)

        # 9. STOP_TOO_CLOSE
        if pool.spot_price > 0:
            distance_to_stop = abs(pool.spot_price - signal.stop_price) / pool.spot_price
            if distance_to_stop < glob["stop_too_close_pct"]:
                failed.append(RiskCheck.STOP_TOO_CLOSE)

        # 10. SELF_PURCHASE
        if buyer_addr.lower() == publisher_addr.lower():
            failed.append(RiskCheck.SELF_PURCHASE)

        # 11. MULTI_TP_INVALID (swing only)
        if profile == "swing" and multi_tp:
            tp1 = signal.metadata["tp1"]
            if not (ref_price < tp1 < signal.target_price):
                failed.append(RiskCheck.MULTI_TP_INVALID)

        # 12. Scalper horizon over-run (defense-in-depth: profile detection should have caught it)
        if profile == "scalper" and signal.horizon_seconds > thresholds["max_horizon_seconds"]:
            failed.append(RiskCheck.STOP_TOO_WIDE)  # reuse closest enum; horizon-too-long is a "stop discipline" failure

        attestation = RiskAttestation(
            signal_id=signal.signal_id,
            **{"pass": len(failed) == 0},
            failed_checks=failed,
            profile=profile,
            appetite=appetite,
            position_size_usd=round(position_size_usd, 2),
            rr_ratio=round(rr, 2),
            expected_slippage_bps=pool.expected_slippage_bps_at_size,
            pool_tvl_usd=pool.tvl_usd,
            spot_twap_deviation=round(spot_twap_dev, 4),
            multi_tp=multi_tp,
            risk_attester=self.attester_ens,
            signature="0x00",
        )
        attestation.signature = sign_risk_attestation(attestation, self.priv_key)

        log.info(
            "risk_check_complete",
            signal_id=signal.signal_id,
            profile=profile,
            appetite=appetite,
            passed=attestation.pass_,
            failed=[c.value for c in failed],
        )
        return attestation
