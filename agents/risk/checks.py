"""
Risk Agent — deterministic checks against a Signal.

Returns a RiskAttestation indicating pass/fail and which checks failed.
Per the signal-validator-spec skill, the thresholds MUST come from
thresholds.json, not hardcoded.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import structlog

from agents.shared.signal_schema import RiskAttestation, RiskCheck, Signal
from agents.shared.signing import sign_risk_attestation

log = structlog.get_logger(__name__)


@dataclass
class PoolMetrics:
    """What we'd query from Uniswap V3 for the signal's token pair."""
    tvl_usd: float
    expected_slippage_bps_at_size: int   # for the proposed capital
    atr_24h: float
    atr_30d_avg: float


class RiskChecker:
    def __init__(self, priv_key: str, attester_ens: str = "risk.sibyl.eth"):
        self.priv_key = priv_key
        self.attester_ens = attester_ens
        self._thresholds = json.loads(
            (Path(__file__).resolve().parent / "thresholds.json").read_text()
        )

    def check(
        self,
        signal: Signal,
        capital_usd: float,
        pool: PoolMetrics,
        buyer_addr: str,
        publisher_addr: str,
    ) -> RiskAttestation:
        failed: list[RiskCheck] = []

        # 1. Position size vs pool TVL
        if capital_usd > pool.tvl_usd * self._thresholds["max_capital_pct_of_pool_tvl"]:
            failed.append(RiskCheck.POSITION_SIZE)

        # 2. Slippage
        if pool.expected_slippage_bps_at_size > self._thresholds["max_slippage_bps"]:
            failed.append(RiskCheck.SLIPPAGE)

        # 3. Volatility sanity
        if pool.atr_30d_avg > 0:
            ratio = pool.atr_24h / pool.atr_30d_avg
            if ratio > self._thresholds["max_volatility_atr_multiple"]:
                failed.append(RiskCheck.VOLATILITY)

        # 4. Liquidity floor
        if pool.tvl_usd < self._thresholds["min_pool_tvl_usd"]:
            failed.append(RiskCheck.LIQUIDITY)

        # 5. Self-purchase (anti-gaming)
        if buyer_addr.lower() == publisher_addr.lower():
            failed.append(RiskCheck.SELF_PURCHASE)

        attestation = RiskAttestation(
            signal_id=signal.signal_id,
            **{"pass": len(failed) == 0},
            failed_checks=failed,
            expected_slippage_bps=pool.expected_slippage_bps_at_size,
            pool_tvl_usd=pool.tvl_usd,
            risk_attester=self.attester_ens,
            signature="0x00",  # placeholder; replaced below
        )

        sig_hex = sign_risk_attestation(attestation, self.priv_key)
        attestation.signature = sig_hex

        log.info(
            "risk_check_complete",
            signal_id=signal.signal_id,
            passed=attestation.pass_,
            failed=[c.value for c in failed],
        )
        return attestation
