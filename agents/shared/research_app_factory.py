"""
FastAPI factory for v2 Research Agents.

The factory wires:
  • x402-paywalled `/signal` endpoint
  • A2A `/.well-known/agent-card.json`
  • Strategy-driven generation; rejection returns 204 (no body).
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Response, status

from .base_research_agent import BaseResearchAgent, PersonaConfig
from .db import close_pool, init_pool
from .logging_setup import setup_logging
from .x402_middleware import PriceConfig, require_payment


def build_research_app(persona: PersonaConfig) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        setup_logging(persona.name)
        await init_pool()
        yield
        await close_pool()

    app = FastAPI(
        title=f"SibylFi Research Agent — {persona.ens_name}",
        version="0.2.0",
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
            "profile": persona.profile,
            "price_per_signal_usdc": persona.price_per_signal_usdc,
        }

    @app.get("/.well-known/agent-card.json")
    async def agent_card():
        return {
            "name": persona.ens_name,
            "description": f"SibylFi Research Agent — {persona.profile} profile",
            "version": "0.2.0",
            "profile": persona.profile,
            "endpoint": f"http://{persona.ens_name}/signal",
            "publishes": ["sibylfi.signal/v2"],
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
        """Generate a fresh signal. 204 if the strategy declines this bar."""
        try:
            signal = await agent.generate_signal(
                token=token,
                published_at_block=12_345_678,   # real mode: query chain head
            )
        except NotImplementedError as e:
            raise HTTPException(status_code=503, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

        if signal is None:
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        return signal.model_dump()

    return app
