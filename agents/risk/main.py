"""
Risk Agent FastAPI service.

Trading Agents POST /verify with a signal + their proposed capital. The Risk
Agent runs deterministic checks and returns a signed attestation.

Paywalled via x402 — the Risk Agent earns a small fee for each verification.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Annotated, Literal

import structlog
from eth_account import Account
from fastapi import Depends, FastAPI
from pydantic import BaseModel

from agents.risk.checks import PoolMetrics, RiskChecker
from agents.shared.db import close_pool, init_pool
from agents.shared.logging_setup import setup_logging
from agents.shared.settings import get_settings
from agents.shared.signal_schema import RiskAttestation, Signal
from agents.shared.x402_middleware import PriceConfig, install_x402_handlers, require_payment

log = structlog.get_logger(__name__)

PRICE_USDC = 0.10  # cheap because it's deterministic and fast


class VerifyRequest(BaseModel):
    signal: Signal
    capital_usd: float
    buyer_addr: str
    publisher_addr: str
    pool: PoolMetrics | None = None  # if None, we use mocks
    appetite: Literal["conservative", "balanced", "aggressive"] = "balanced"


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging("risk-agent")
    await init_pool()
    yield
    await close_pool()


app = FastAPI(title="SibylFi Risk Agent", version="0.1.0", lifespan=lifespan)
install_x402_handlers(app)
_settings = get_settings()
_addr = Account.from_key(_settings.RISK_KEY).address
_checker = RiskChecker(priv_key=_settings.RISK_KEY)
_price = PriceConfig(usdc=PRICE_USDC, recipient_addr=_addr)


@app.get("/")
async def root():
    return {"ens": "risk.sibylfi.eth", "address": _addr, "price_per_check_usdc": PRICE_USDC}


@app.get("/.well-known/agent-card.json")
async def agent_card():
    return {
        "name": "risk.sibylfi.eth",
        "description": "SibylFi Risk Agent — deterministic verification of signals before execution",
        "version": "0.1.0",
        "endpoint": "/verify",
        "publishes": ["sibylfi.risk-attestation/v1"],
        "payment": {
            "scheme": "x402",
            "asset": "USDC",
            "network": "base-sepolia",
            "price": str(PRICE_USDC),
        },
    }


@app.post(
    "/verify",
    response_model=RiskAttestation,
    dependencies=[Depends(require_payment(_price))],
)
async def verify(req: VerifyRequest):
    pool = req.pool or _mock_pool_metrics(req.signal.entry_condition.reference_price)
    return _checker.check(
        signal=req.signal,
        capital_usd=req.capital_usd,
        pool=pool,
        buyer_addr=req.buyer_addr,
        publisher_addr=req.publisher_addr,
        appetite=req.appetite,
    )


def _mock_pool_metrics(reference_price: float = 3500.0) -> PoolMetrics:
    """Mock pool metrics. In real mode, query Uniswap V3 subgraph."""
    tvl = 2_500_000.0
    return PoolMetrics(
        tvl_usd=tvl,
        expected_slippage_bps_at_size=8,
        atr_24h=0.012,
        atr_30d_avg=0.010,
        exhaustion_cost=tvl * 0.5,
        spot_price=reference_price,
        twap_30m=reference_price,
    )
