"""
Trading Agent FastAPI — exposes /trade for orchestrator and demo control.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from agents.shared.db import close_pool, init_pool
from agents.shared.logging_setup import setup_logging
from agents.trading.agent import TradingAgent


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging("trading-agent")
    await init_pool()
    yield
    await close_pool()


app = FastAPI(title="SibylFi Trading Agent", version="0.1.0", lifespan=lifespan)
_agent = TradingAgent()


@app.get("/")
async def root():
    return {"address": _agent.address, "role": "trading"}


@app.post("/trade")
async def trade(token: str = "WETH/USDC", capital_usd: float = 1000.0):
    """
    Run the discover → buy → risk → execute pipeline once.
    Returns the trade result for inspection.
    """
    result = await _agent.discover_and_trade(token=token, capital_usd=capital_usd)
    return {
        "signal_id": result.signal.signal_id if result.signal else None,
        "publisher": result.signal.publisher if result.signal else None,
        "direction": result.signal.direction if result.signal else None,
        "risk_passed": result.risk.pass_ if result.risk else None,
        "skipped_reason": result.skipped_reason,
        "tx_hash": result.swap.tx_hash if result.swap else None,
        "gas_used": result.swap.gas_used if result.swap else None,
    }
