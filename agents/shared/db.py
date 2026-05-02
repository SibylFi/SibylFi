"""
Postgres connection pool + schema management.

Schema is auto-applied on startup if tables don't exist. For production-grade
migrations you'd want Alembic, but for a hackathon repo this is fine.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

import psycopg
import structlog
from psycopg_pool import AsyncConnectionPool

from .settings import get_settings

log = structlog.get_logger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
    signal_id         TEXT PRIMARY KEY,
    publisher         TEXT NOT NULL,
    publisher_addr    TEXT NOT NULL,
    token             TEXT NOT NULL,
    direction         TEXT NOT NULL,
    reference_price   DOUBLE PRECISION NOT NULL,
    target_price      DOUBLE PRECISION NOT NULL,
    stop_price        DOUBLE PRECISION NOT NULL,
    horizon_seconds   INTEGER NOT NULL,
    confidence_bps    INTEGER NOT NULL,
    published_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    horizon_expires_at TIMESTAMPTZ NOT NULL,
    raw_payload       JSONB NOT NULL,
    settled           BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS executions (
    id                BIGSERIAL PRIMARY KEY,
    signal_id         TEXT NOT NULL REFERENCES signals(signal_id),
    buyer_addr        TEXT NOT NULL,
    capital_usd       DOUBLE PRECISION NOT NULL,
    actual_fill_price DOUBLE PRECISION NOT NULL,
    twap_at_execution DOUBLE PRECISION NOT NULL,
    gas_used          BIGINT NOT NULL,
    executed_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    tx_hash           TEXT
);

CREATE TABLE IF NOT EXISTS settlements (
    signal_id         TEXT PRIMARY KEY REFERENCES signals(signal_id),
    publisher         TEXT NOT NULL,
    outcome           TEXT NOT NULL,
    pnl_bps_gross     INTEGER NOT NULL,
    pnl_bps_net       INTEGER NOT NULL,
    gas_bps           INTEGER NOT NULL,
    execution_loss_bps INTEGER NOT NULL,
    signal_loss_bps   INTEGER NOT NULL,
    twap_at_horizon   DOUBLE PRECISION NOT NULL,
    capital_deployed_usd DOUBLE PRECISION NOT NULL,
    distinct_buyers   INTEGER NOT NULL,
    self_purchase_detected BOOLEAN NOT NULL,
    settled_at_block  BIGINT NOT NULL,
    settled_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    onchain_tx_hash   TEXT
);

CREATE TABLE IF NOT EXISTS x402_payments (
    id                BIGSERIAL PRIMARY KEY,
    payer_addr        TEXT NOT NULL,
    recipient_addr    TEXT NOT NULL,
    amount_usdc       DOUBLE PRECISION NOT NULL,
    nonce             TEXT UNIQUE NOT NULL,
    paid_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_signals_horizon ON signals(horizon_expires_at) WHERE settled = FALSE;
CREATE INDEX IF NOT EXISTS idx_executions_signal ON executions(signal_id);
"""

_pool: AsyncConnectionPool | None = None


async def init_pool() -> AsyncConnectionPool:
    global _pool
    if _pool is not None:
        return _pool
    settings = get_settings()
    _pool = AsyncConnectionPool(
        conninfo=settings.database_url,
        min_size=1,
        max_size=10,
        open=False,
    )
    await _pool.open()
    await _ensure_schema()
    log.info("db_pool_initialized")
    return _pool


async def _ensure_schema() -> None:
    assert _pool is not None
    async with _pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(SCHEMA)
        await conn.commit()
    log.info("db_schema_ensured")


@asynccontextmanager
async def db_conn() -> AsyncIterator[psycopg.AsyncConnection]:
    if _pool is None:
        raise RuntimeError("DB pool not initialized — call init_pool() at app startup")
    async with _pool.connection() as conn:
        yield conn


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
