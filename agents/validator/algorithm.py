"""
Validator Agent algorithm.

The deterministic on-chain settlement oracle for SibylFi signals.
This is the core technical contribution of the project.

Implements the rules from .claude/skills/signal-validator-spec/SKILL.md plus v2:
  - Long-only (short is rejected upstream; defense-in-depth assert here)
  - Multi-checkpoint TWAP path: WIN_PARTIAL fires when TP1 hits before stop
    and stop hits before target (swing multi-TP)
  - INCONCLUSIVE outcome when oracle data is missing/empty
  - Reference price = price at publication block (NOT execution price)
  - Gas-adjusted PnL: net = gross - gas_bps
  - Slippage attribution: split signal-loss vs execution-loss
  - Capital-weighted reputation: weight = sqrt(capital_usd) / 100
  - Cold-start: half-weight for newcomer agents (< 5 settled signals)
  - Anti-gaming: muted if no distinct buyers; self-purchase excluded
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import structlog

from agents.shared.signal_schema import Outcome, Settlement, Signal

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class Checkpoint:
    """A single TWAP sample inside the signal's horizon window."""
    price: float
    t: int   # seconds elapsed since signal publication


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
    checkpoints: list[Checkpoint]    # NEW: path-aware multi-sample TWAP
    executions: list[ExecutionRecord]
    eth_usd_at_horizon: float
    base_sepolia_gas_price_wei: int
    settled_at_block: int
    settled_at_timestamp: int

    @property
    def twap_at_horizon(self) -> float:
        """Backward-compat: the horizon-end TWAP is the last checkpoint's price."""
        return self.checkpoints[-1].price if self.checkpoints else 0.0


# ─────────────────────────────────────────────────────────────────────────
# Core algorithm
# ─────────────────────────────────────────────────────────────────────────

def settle(inputs: SettlementInputs) -> Settlement:
    """Deterministic settlement. Long-only in v2."""
    signal = inputs.signal
    assert signal.direction == "long", "v2 is long-only; signal must be rejected upstream"

    # ─── 1. Determine outcome (multi-checkpoint, may emit WIN_PARTIAL or INCONCLUSIVE)
    outcome = _outcome(signal, inputs.checkpoints)

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

    twap_at_horizon = inputs.twap_at_horizon

    # ─── 3. PnL (only meaningful for terminal, capitalized outcomes)
    skip_pnl = outcome in (Outcome.EXPIRED, Outcome.INCONCLUSIVE, Outcome.INVALID) or total_capital_usd == 0
    if skip_pnl:
        pnl_gross = pnl_net = gas_bps = exec_loss = sig_loss = 0
    else:
        # For WIN_PARTIAL, PnL is computed against TP1 (intermediate exit).
        # For WIN/LOSS, PnL is computed against the horizon-end TWAP.
        if outcome == Outcome.WIN_PARTIAL and signal.metadata and "tp1" in signal.metadata:
            settle_price = float(signal.metadata["tp1"])
        else:
            settle_price = twap_at_horizon

        pnl_gross = _gross_pnl_bps(
            ref_price=signal.entry_condition.reference_price,
            twap=settle_price,
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
        twap_at_horizon=twap_at_horizon,
        capital_deployed_usd=total_capital_usd,
        distinct_buyers=distinct_buyers,
        self_purchase_detected=self_purchase,
        settled_at_block=inputs.settled_at_block,
        settled_at_timestamp=inputs.settled_at_timestamp,
    )


# ─────────────────────────────────────────────────────────────────────────
# Sub-rules (each pure, individually testable)
# ─────────────────────────────────────────────────────────────────────────

def _outcome(signal: Signal, checkpoints: list[Checkpoint]) -> Outcome:
    """
    Path-aware outcome resolver. v2 long-only.

    Walks the checkpoint sequence and reports the first terminal event that
    fires:
      - target hit (before stop) → WIN
      - tp1 hit (before stop) but stop hits before target → WIN_PARTIAL
      - stop hit (before target) → LOSS
      - neither hit by the last checkpoint → EXPIRED
      - empty checkpoints (oracle gap) → INCONCLUSIVE

    Convention on ties: stop wins (Elder: conservative).
    """
    if not checkpoints:
        return Outcome.INCONCLUSIVE

    target = signal.target_price
    stop   = signal.stop_price
    tp1    = (signal.metadata or {}).get("tp1") if signal.metadata else None

    hit_target = next((c.t for c in checkpoints if c.price >= target), None)
    hit_stop   = next((c.t for c in checkpoints if c.price <= stop),   None)
    hit_tp1    = next((c.t for c in checkpoints if tp1 and c.price >= tp1), None) if tp1 else None

    if hit_target is not None and (hit_stop is None or hit_target < hit_stop):
        return Outcome.WIN
    if hit_tp1 is not None and hit_stop is not None and hit_tp1 < hit_stop:
        return Outcome.WIN_PARTIAL
    if hit_stop is not None:
        return Outcome.LOSS
    return Outcome.EXPIRED


def _gross_pnl_bps(ref_price: float, twap: float) -> int:
    """Gross PnL in basis points (long-only: positive when price rises)."""
    if ref_price <= 0:
        return 0
    return int(((twap - ref_price) / ref_price) * 10000)


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
        total_gas_usd += gas_eth * eth_usd
    return int((total_gas_usd / total_capital_usd) * 10000)


def _attribute_slippage(
    executions: list[ExecutionRecord],
    pnl_net: int,
) -> tuple[int, int]:
    """
    Returns (execution_loss_bps, signal_loss_bps). Long-only.

    Execution loss = how much worse the buyer's actual fill was vs the TWAP-
    at-execution. Buyer's fault, not publisher's.

    Signal loss = whatever's left of the negative PnL after carving out
    execution loss.
    """
    if pnl_net >= 0 or not executions:
        return (0, 0)

    total_capital = sum(e.capital_usd for e in executions)
    if total_capital <= 0:
        return (0, abs(pnl_net))

    weighted_exec_loss_bps = 0.0
    for e in executions:
        if e.twap_at_execution <= 0:
            continue
        # Long: "bad fill" = paid more than TWAP-at-execution
        delta_bps = (e.actual_fill_price - e.twap_at_execution) / e.twap_at_execution * 10000
        exec_loss = max(0.0, delta_bps)
        weighted_exec_loss_bps += exec_loss * (e.capital_usd / total_capital)

    exec_loss_int = int(weighted_exec_loss_bps)
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

    v2 rules:
      - Mute if no distinct buyers (anti-spam-attack)
      - Mute if self-purchase detected
      - EXPIRED / INCONCLUSIVE / INVALID short-circuit to (0, 0)
      - WIN_PARTIAL gives half-credit on positive PnL
      - delta_score uses signal_loss_bps for losses (execution loss is buyer's fault)
      - weight = sqrt(capital_usd) / 100 (×100 scaled int)
      - Cold-start agents get half-weight
      - Clamp delta_score to ±50 bps
    """
    if settlement.distinct_buyers < 2 or settlement.self_purchase_detected:
        return (0, 0)

    if settlement.outcome in (Outcome.EXPIRED, Outcome.INCONCLUSIVE, Outcome.INVALID, Outcome.PENDING):
        return (0, 0)

    if settlement.outcome == Outcome.WIN:
        signed_pnl_bps = max(0, settlement.pnl_bps_net)
    elif settlement.outcome == Outcome.WIN_PARTIAL:
        # Half credit: TP1 hit but stopped before TP2 — partial but real win
        signed_pnl_bps = max(0, settlement.pnl_bps_net // 2)
    else:  # LOSS
        signed_pnl_bps = -settlement.signal_loss_bps

    weight = int(math.sqrt(settlement.capital_deployed_usd) / 100 * 100)
    if is_cold_start:
        weight = weight // 2

    contribution = max(-50, min(50, signed_pnl_bps // 100))
    delta_score = contribution * weight // 100

    return (delta_score, weight)
