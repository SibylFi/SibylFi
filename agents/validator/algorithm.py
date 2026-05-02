"""
Validator Agent algorithm.

The deterministic on-chain settlement oracle for SibylFi signals.
This is the core technical contribution of the project.

Implements the rules from .claude/skills/signal-validator-spec/SKILL.md:
  - 5-minute Uniswap V3 TWAP read at horizon-end
  - Reference price = price at publication block (NOT execution price)
  - Gas-adjusted PnL: net = gross - gas_bps
  - Slippage attribution: split signal-loss vs execution-loss
  - Capital-weighted reputation: weight = sqrt(capital_usd) / 100
  - Cold-start: half-weight for newcomer agents (< 5 settled signals)
  - Anti-gaming: muted if no distinct buyers; self-purchase excluded
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import structlog

from agents.shared.signal_schema import Outcome, Settlement, Signal

log = structlog.get_logger(__name__)


@dataclass
class ExecutionRecord:
    """One buyer's execution of a signal — all needed data for settlement."""
    buyer_addr: str
    capital_usd: float
    actual_fill_price: float
    twap_at_execution: float
    gas_used: int


@dataclass
class SettlementInputs:
    """All the data the Validator needs to settle a signal."""
    signal: Signal
    publisher_addr: str
    twap_at_horizon: float           # 5-min TWAP ending at horizon-end
    executions: list[ExecutionRecord]
    eth_usd_at_horizon: float
    base_sepolia_gas_price_wei: int
    settled_at_block: int
    settled_at_timestamp: int


# ─────────────────────────────────────────────────────────────────────────
# Core algorithm
# ─────────────────────────────────────────────────────────────────────────

def settle(inputs: SettlementInputs) -> Settlement:
    """
    Deterministic settlement.

    Returns a Settlement record. Caller (Validator service) is responsible for
    posting the on-chain transaction and writing to the settlements table.
    """
    signal = inputs.signal
    direction_sign = 1 if signal.direction == "long" else -1

    # ─── 1. Determine outcome (target/stop hit, or expired)
    outcome = _outcome(
        signal=signal,
        twap_at_horizon=inputs.twap_at_horizon,
        direction_sign=direction_sign,
    )

    # ─── 2. Compute aggregate executions (excluding self-purchases)
    self_purchase = any(
        e.buyer_addr.lower() == inputs.publisher_addr.lower()
        for e in inputs.executions
    )
    valid = [
        e for e in inputs.executions
        if e.buyer_addr.lower() != inputs.publisher_addr.lower()
    ]
    distinct_buyers = len({e.buyer_addr.lower() for e in valid})
    total_capital_usd = sum(e.capital_usd for e in valid) or 0.0

    # ─── 3. PnL computation (only meaningful if not expired and there's capital)
    if outcome == Outcome.EXPIRED or total_capital_usd == 0:
        pnl_gross = pnl_net = gas_bps = exec_loss = sig_loss = 0
    else:
        pnl_gross = _gross_pnl_bps(
            ref_price=signal.entry_condition.reference_price,
            twap=inputs.twap_at_horizon,
            direction_sign=direction_sign,
        )

        gas_bps = _gas_bps(
            executions=valid,
            eth_usd=inputs.eth_usd_at_horizon,
            gas_price_wei=inputs.base_sepolia_gas_price_wei,
            total_capital_usd=total_capital_usd,
        )

        pnl_net = pnl_gross - gas_bps

        exec_loss, sig_loss = _attribute_slippage(
            executions=valid,
            twap_at_horizon=inputs.twap_at_horizon,
            direction_sign=direction_sign,
            pnl_net=pnl_net,
        )

    # ─── 4. Build settlement record
    return Settlement(
        signal_id=signal.signal_id,
        publisher=signal.publisher,
        outcome=outcome,
        pnl_bps_gross=pnl_gross,
        pnl_bps_net=pnl_net,
        gas_bps=gas_bps,
        execution_loss_bps=exec_loss,
        signal_loss_bps=sig_loss,
        twap_at_horizon=inputs.twap_at_horizon,
        capital_deployed_usd=total_capital_usd,
        distinct_buyers=distinct_buyers,
        self_purchase_detected=self_purchase,
        settled_at_block=inputs.settled_at_block,
        settled_at_timestamp=inputs.settled_at_timestamp,
    )


# ─────────────────────────────────────────────────────────────────────────
# Sub-rules (each pure, individually testable)
# ─────────────────────────────────────────────────────────────────────────

def _outcome(signal: Signal, twap_at_horizon: float, direction_sign: int) -> Outcome:
    """
    Win if the TWAP reached target before stop. Loss if stop hit. Expired
    if neither.

    Simplified for v1: we don't have an intra-horizon path, so we compare the
    horizon-end TWAP to target/stop directly. A future version with an
    indexed price feed could check whether target was reached at any point
    during the horizon BEFORE the stop was reached.

    This v1 simplification is documented and intentional.
    """
    if direction_sign > 0:  # long
        if twap_at_horizon >= signal.target_price:
            return Outcome.WIN
        if twap_at_horizon <= signal.stop_price:
            return Outcome.LOSS
        return Outcome.EXPIRED
    else:  # short
        if twap_at_horizon <= signal.target_price:
            return Outcome.WIN
        if twap_at_horizon >= signal.stop_price:
            return Outcome.LOSS
        return Outcome.EXPIRED


def _gross_pnl_bps(ref_price: float, twap: float, direction_sign: int) -> int:
    """Gross PnL in basis points, signed by direction."""
    return int(((twap - ref_price) / ref_price) * 10000 * direction_sign)


def _gas_bps(
    executions: list[ExecutionRecord],
    eth_usd: float,
    gas_price_wei: int,
    total_capital_usd: float,
) -> int:
    """Capital-weighted average of gas-as-fraction-of-capital, in bps."""
    if not executions or total_capital_usd <= 0:
        return 0

    total_gas_usd = 0.0
    for e in executions:
        gas_eth = (e.gas_used * gas_price_wei) / 1e18
        gas_usd = gas_eth * eth_usd
        total_gas_usd += gas_usd

    return int((total_gas_usd / total_capital_usd) * 10000)


def _attribute_slippage(
    executions: list[ExecutionRecord],
    twap_at_horizon: float,
    direction_sign: int,
    pnl_net: int,
) -> tuple[int, int]:
    """
    Returns (execution_loss_bps, signal_loss_bps).

    Execution loss = how much worse the buyer's actual fill was vs the TWAP-
    at-execution. This is buyer's fault, not publisher's.

    Signal loss = whatever's left of the negative PnL after carving out
    execution loss.

    The two numbers add up to the non-positive component of pnl_net. Positive
    PnL has no loss to attribute.
    """
    if pnl_net >= 0 or not executions:
        return (0, 0)

    # Capital-weighted execution loss
    total_capital = sum(e.capital_usd for e in executions)
    if total_capital <= 0:
        return (0, pnl_net)

    weighted_exec_loss_bps = 0.0
    for e in executions:
        # In a long, "bad fill" means actual_fill > twap_at_execution.
        # In a short, "bad fill" means actual_fill < twap_at_execution.
        if e.twap_at_execution <= 0:
            continue
        delta_bps = (e.actual_fill_price - e.twap_at_execution) / e.twap_at_execution * 10000
        if direction_sign > 0:
            exec_loss = max(0.0, delta_bps)  # paid more than TWAP
        else:
            exec_loss = max(0.0, -delta_bps)  # got less than TWAP
        weighted_exec_loss_bps += exec_loss * (e.capital_usd / total_capital)

    exec_loss_int = int(weighted_exec_loss_bps)
    # Don't attribute MORE execution loss than there is total negative PnL
    exec_loss_int = min(exec_loss_int, abs(pnl_net))
    sig_loss_int = abs(pnl_net) - exec_loss_int
    return exec_loss_int, sig_loss_int


# ─────────────────────────────────────────────────────────────────────────
# Reputation update (informational)
# ─────────────────────────────────────────────────────────────────────────

def reputation_update(
    settlement: Settlement,
    is_cold_start: bool,
) -> tuple[int, int]:
    """
    Returns (delta_score, weight) suitable for posting to ERC-8004.attest().

    Rules:
      - Mute if no distinct buyers (anti-spam-attack)
      - Mute if self-purchase detected
      - delta_score uses signal_loss_bps (NOT pnl_bps_net) — execution loss is buyer's fault
      - weight = sqrt(capital_usd) / 100
      - Cold-start agents get half-weight
      - Clamp delta_score to ±50 bps to prevent one giant signal dominating
    """
    if settlement.distinct_buyers < 2 or settlement.self_purchase_detected:
        return (0, 0)

    if settlement.outcome == Outcome.EXPIRED:
        return (0, 0)

    # Use signal_loss for losses; positive PnL net for wins (publisher gets full credit on wins
    # because gas/slippage doesn't reduce the publisher's accuracy, just the buyer's net return).
    # DECISION: this is debatable; an alternate rule punishes publishers proportionally for high-gas signals.
    if settlement.outcome == Outcome.WIN:
        signed_pnl_bps = max(0, settlement.pnl_bps_net)
    else:
        signed_pnl_bps = -settlement.signal_loss_bps

    weight = int(math.sqrt(settlement.capital_deployed_usd) / 100 * 100)  # scaled int (×100)
    if is_cold_start:
        weight = weight // 2

    # Clamp the bps contribution
    contribution = max(-50, min(50, signed_pnl_bps // 100))  # bps → percent → clamped
    delta_score = contribution * weight // 100  # de-scale weight

    return (delta_score, weight)
