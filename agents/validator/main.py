"""
Validator service — finds expired signals and settles them.

Runs as an APScheduler cron inside FastAPI. Every 30 seconds:
  1. Query Postgres for signals with horizon_expires_at < NOW() and not yet settled
  2. For each: load executions, read TWAP, run algorithm, persist settlement
  3. Post attestation to ERC-8004 ReputationRegistry
  4. Mark signal settled

In real mode this also posts to ValidatorSettle.sol on Base Sepolia. In mock,
that's a logged no-op.
"""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from eth_account import Account
from fastapi import FastAPI

from agents.shared.db import close_pool, db_conn, init_pool
from agents.shared.erc8004_client import ERC8004Client
from agents.shared.logging_setup import setup_logging
from agents.shared.settings import get_settings
from agents.shared.signal_schema import Signal
from agents.validator.algorithm import (
    ExecutionRecord,
    SettlementInputs,
    reputation_update,
    settle,
)
from agents.validator.twap import read_checkpoints

log = structlog.get_logger(__name__)


_scheduler: AsyncIOScheduler | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging("validator-agent")
    await init_pool()
    global _scheduler
    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(_settle_loop, "interval", seconds=30, id="settle_loop")
    _scheduler.start()
    log.info("validator_scheduler_started")
    yield
    if _scheduler:
        _scheduler.shutdown(wait=False)
    await close_pool()


app = FastAPI(title="SibylFi Validator", version="0.1.0", lifespan=lifespan)
_settings = get_settings()
_address = Account.from_key(_settings.VALIDATOR_KEY).address
_erc8004 = ERC8004Client(signer_priv_key=_settings.VALIDATOR_KEY)


@app.get("/")
async def root():
    return {"address": _address, "role": "validator"}


@app.get("/status")
async def status():
    """How many signals are pending settlement?"""
    async with db_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT
                  COUNT(*) FILTER (WHERE settled = FALSE AND horizon_expires_at < NOW()) AS due_now,
                  COUNT(*) FILTER (WHERE settled = FALSE) AS unsettled_total,
                  COUNT(*) FILTER (WHERE settled = TRUE) AS settled_total
                FROM signals
                """
            )
            row = await cur.fetchone()
    return {"due_now": row[0], "unsettled_total": row[1], "settled_total": row[2]}


@app.post("/settle-now")
async def settle_now():
    """Manual trigger; useful for demo recording."""
    count = await _settle_loop()
    return {"settled": count}


# ─────────────────────────────────────────────────────────────────────────
# Settlement loop
# ─────────────────────────────────────────────────────────────────────────

async def _settle_loop() -> int:
    """Returns count of signals settled this iteration."""
    settled = 0
    try:
        async with db_conn() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT signal_id, raw_payload
                    FROM signals
                    WHERE settled = FALSE AND horizon_expires_at < NOW()
                    ORDER BY horizon_expires_at ASC
                    LIMIT 10
                    """
                )
                rows = await cur.fetchall()

        for row in rows:
            signal_id, payload_text = row[0], row[1]
            payload = payload_text if isinstance(payload_text, dict) else json.loads(payload_text)
            try:
                signal = Signal(**payload)
                await _settle_one(signal)
                settled += 1
            except Exception as e:
                log.error("settle_failed", signal_id=signal_id, error=str(e))
    except Exception as e:
        log.error("settle_loop_error", error=str(e))
    return settled


async def _settle_one(signal: Signal) -> None:
    """Settle a single signal end-to-end."""
    # 1. Look up the publisher's address (for self-purchase check)
    publisher_addr = await _publisher_addr(signal)

    # 2. Load executions
    executions = await _load_executions(signal.signal_id)

    # 3. Read multi-checkpoint TWAP path through the horizon window
    token_pair = signal.token  # e.g. "WETH/USDC" — in real mode, parse CAIP-19 + look up pool
    if "/" not in token_pair:
        token_pair = "WETH/USDC"  # fallback for malformed tokens
    checkpoints = read_checkpoints(
        token=token_pair,
        published_at_block=signal.published_at_block,
        horizon_seconds=signal.horizon_seconds,
        n_checkpoints=5,
    )

    # 4. Run the algorithm — pull live chain values from Base Sepolia (gas
    # price, head block) and the closing TWAP checkpoint as the ETH/USD
    # reference. In MOCK_MODE _read_chain_context returns deterministic stubs
    # so unit tests stay reproducible.
    eth_usd, gas_price_wei, head_block = _read_chain_context(checkpoints)
    settlement = settle(SettlementInputs(
        signal=signal,
        publisher_addr=publisher_addr,
        checkpoints=checkpoints,
        executions=executions,
        eth_usd_at_horizon=eth_usd,
        base_sepolia_gas_price_wei=gas_price_wei,
        settled_at_block=head_block,
        settled_at_timestamp=int(datetime.now(timezone.utc).timestamp()),
    ))

    # 5. Persist settlement
    await _persist_settlement(settlement)

    # 6. Post on-chain attestation (if any reputation change)
    agent_id = await _publisher_agent_id(signal)
    is_cold_start = await _is_cold_start(agent_id)
    delta, weight = reputation_update(settlement, is_cold_start)

    tx_hash = ""
    if delta != 0 and weight > 0:
        signal_id_bytes = bytes.fromhex(signal.signal_id.removeprefix("0x"))
        tx_hash = _erc8004.attest(
            agent_id=agent_id,
            signal_id=signal_id_bytes,
            win=settlement.outcome.value == "win",
            pnl_bps=settlement.pnl_bps_net,
            weight=weight,
        )

    log.info(
        "signal_settled",
        signal_id=signal.signal_id,
        outcome=settlement.outcome.value,
        pnl_net_bps=settlement.pnl_bps_net,
        delta_score=delta,
        weight=weight,
        tx_hash=tx_hash,
    )


# ─────────────────────────────────────────────────────────────────────────
# Chain context helpers
# ─────────────────────────────────────────────────────────────────────────

_w3_base_sepolia = None


def _get_base_sepolia_w3():
    """Lazy-init a Base Sepolia web3 client for reading gas price + head block."""
    global _w3_base_sepolia
    if _w3_base_sepolia is None:
        from web3 import Web3
        _w3_base_sepolia = Web3(Web3.HTTPProvider(get_settings().BASE_SEPOLIA_RPC))
    return _w3_base_sepolia


def _read_chain_context(checkpoints) -> tuple[float, int, int]:
    """
    Returns (eth_usd_at_horizon, gas_price_wei, head_block_number).

    eth_usd_at_horizon comes from the closing TWAP checkpoint — that's the
    same on-chain pool we already read for path PnL, so the price is
    consistent with the settlement input.
    gas_price_wei + head_block come from the live Base Sepolia node.

    In MOCK_MODE we use stable stubs so unit tests stay deterministic.
    """
    settings = get_settings()
    if settings.MOCK_MODE or not checkpoints:
        return 3450.0, 1_000_000_000, 12_345_900

    # Closing checkpoint = last entry; .price is the WETH→USDC decimal-adjusted
    # spot from the same on-chain TWAP we use for path PnL, so the figure is
    # internally consistent with the rest of the settlement input.
    closing = checkpoints[-1]
    eth_usd = float(getattr(closing, "price", 0)) or 3450.0

    try:
        w3 = _get_base_sepolia_w3()
        gas_price_wei = int(w3.eth.gas_price)
        head_block = int(w3.eth.block_number)
    except Exception as e:
        log.warning("validator_chain_context_read_failed", error=str(e))
        # Fall back to mock for these two numerical inputs only — the
        # algorithm needs *some* value, and we'd rather settle than block.
        gas_price_wei, head_block = 1_000_000_000, 12_345_900

    return eth_usd, gas_price_wei, head_block


# ─────────────────────────────────────────────────────────────────────────
# DB helpers
# ─────────────────────────────────────────────────────────────────────────

async def _publisher_addr(signal: Signal) -> str:
    """Look up the publisher's wallet address from the signal log."""
    async with db_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT publisher_addr FROM signals WHERE signal_id = %s",
                (signal.signal_id,),
            )
            row = await cur.fetchone()
            return row[0] if row else "0x0"


async def _publisher_agent_id(signal: Signal) -> int:
    """Map ENS name to ERC-8004 agent ID."""
    agents = _erc8004.list_agents()
    for a in agents:
        if a.ens_name == signal.publisher:
            return a.agent_id
    log.warning("publisher_agent_id_not_found", ens=signal.publisher)
    return 0


async def _is_cold_start(agent_id: int) -> bool:
    """An agent is cold-start until they've had >= 5 settled signals."""
    if agent_id == 0:
        return True
    stats = _erc8004.get_stats(agent_id)
    return stats.total_attestations < 5


async def _load_executions(signal_id: str) -> list[ExecutionRecord]:
    async with db_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT buyer_addr, capital_usd, actual_fill_price, twap_at_execution, gas_used
                FROM executions
                WHERE signal_id = %s
                """,
                (signal_id,),
            )
            rows = await cur.fetchall()
    return [
        ExecutionRecord(
            buyer_addr=r[0],
            capital_usd=float(r[1]),
            actual_fill_price=float(r[2]),
            twap_at_execution=float(r[3]),
            gas_used=int(r[4]),
        )
        for r in rows
    ]


async def _persist_settlement(s) -> None:
    async with db_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO settlements (
                    signal_id, publisher, outcome,
                    pnl_bps_gross, pnl_bps_net, gas_bps,
                    execution_loss_bps, signal_loss_bps,
                    twap_at_horizon, capital_deployed_usd, distinct_buyers,
                    self_purchase_detected, settled_at_block
                ) VALUES (
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s,
                    %s, %s, %s,
                    %s, %s
                )
                ON CONFLICT (signal_id) DO NOTHING
                """,
                (
                    s.signal_id, s.publisher, s.outcome.value,
                    s.pnl_bps_gross, s.pnl_bps_net, s.gas_bps,
                    s.execution_loss_bps, s.signal_loss_bps,
                    s.twap_at_horizon, s.capital_deployed_usd, s.distinct_buyers,
                    s.self_purchase_detected, s.settled_at_block,
                ),
            )
            await cur.execute(
                "UPDATE signals SET settled = TRUE WHERE signal_id = %s",
                (s.signal_id,),
            )
            await conn.commit()
