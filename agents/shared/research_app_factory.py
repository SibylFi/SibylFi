"""
FastAPI factory for Research Agents.

Each persona's main.py imports build_app(persona_config) and uvicorn runs it.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException

from .base_research_agent import BaseResearchAgent, PersonaConfig
from .db import close_pool, init_pool
from .logging_setup import setup_logging
from .x402_middleware import PriceConfig, require_payment


def build_research_app(persona: PersonaConfig) -> FastAPI:
    """Construct the FastAPI app for a Research Agent persona."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        setup_logging(persona.name)
        await init_pool()
        yield
        await close_pool()

    app = FastAPI(
        title=f"SibylFi Research Agent — {persona.ens_name}",
        version="0.1.0",
        lifespan=lifespan,
    )
    agent = BaseResearchAgent(persona)

    price = PriceConfig(
        usdc=persona.price_per_signal_usdc,
        recipient_addr=agent.address,
    )

    @app.get("/")
    async def root():
        return {
            "ens": persona.ens_name,
            "address": agent.address,
            "price_per_signal_usdc": persona.price_per_signal_usdc,
            "horizon_seconds": persona.horizon_seconds,
        }

    @app.get("/.well-known/agent-card.json")
    async def agent_card():
        """A2A protocol-compliant agent card."""
        return {
            "name": persona.ens_name,
            "description": f"SibylFi Research Agent — {persona.name} persona",
            "version": "0.1.0",
            "endpoint": f"http://{persona.ens_name}/signal",
            "publishes": ["sibylfi.signal/v1"],
            "payment": {
                "scheme": "x402",
                "asset": "USDC",
                "network": "base-sepolia",
                "price": str(persona.price_per_signal_usdc),
            },
        }

    @app.get(
        "/signal",
        dependencies=[Depends(require_payment(price))],
    )
    async def get_signal(token: str = "WETH/USDC"):
        """
        Generate a fresh signal. Paywalled via x402.
        """
        try:
            signal = await agent.generate_signal(
                token=token,
                reference_price=_mock_reference_price(token),
                published_at_block=12_345_678,  # in real mode, query the chain
            )
            return signal.model_dump()
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    return app


def _mock_reference_price(token: str) -> float:
    """Look up a reference price from the TWAP fixtures. In real mode, query Uniswap V3."""
    import json
    from pathlib import Path
    fixtures = json.loads(
        (Path(__file__).resolve().parent / "mocks" / "twap_fixtures.json").read_text()
    )
    if token in fixtures:
        return fixtures[token]["ref_price"]
    return 1.0  # safe default
