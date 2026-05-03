"""
x402 server middleware for SibylFi paid endpoints.

Drop this dependency on any FastAPI route to require a micropayment:

    from agents.shared.x402_middleware import require_payment, PriceConfig

    @app.get("/signal", dependencies=[Depends(require_payment(PriceConfig(usdc=0.50)))])
    async def get_signal():
        ...

In MOCK_MODE, the dependency accepts any non-empty X-PAYMENT header and skips
facilitator verification. This lets the full pipeline run offline.

See x402-and-uniswap skill in .claude/skills/.
"""
import json
from dataclasses import dataclass
from typing import Callable, Optional

import httpx
import structlog
from fastapi import Header, HTTPException, Request, Response

from .settings import get_settings

log = structlog.get_logger(__name__)


@dataclass
class PriceConfig:
    """Per-endpoint pricing configuration."""
    usdc: float                              # price in USDC (will be converted to 6-decimal int)
    recipient_addr: str = ""                 # if empty, looked up from Settings per agent
    network: str = "base-sepolia"
    max_timeout_seconds: int = 300

    def usdc_micro_amount(self) -> int:
        """Returns price in USDC's smallest unit (USDC has 6 decimals)."""
        return int(self.usdc * 1_000_000)


def _build_402_response(price: PriceConfig, recipient: str) -> Response:
    settings = get_settings()
    body = {
        "x402_version": 1,
        "accepts": [
            {
                "scheme": "exact",
                "network": price.network,
                "asset": settings.USDC_BASE_SEPOLIA,
                "max_amount_required": str(price.usdc_micro_amount()),
                "pay_to": recipient,
                "max_timeout_seconds": price.max_timeout_seconds,
            }
        ],
    }
    return Response(
        status_code=402,
        content=json.dumps(body),
        media_type="application/json",
    )


async def _verify_with_facilitator(payment_header: str) -> bool:
    """Calls Coinbase CDP facilitator to verify the X-PAYMENT header."""
    settings = get_settings()
    url = f"{settings.X402_FACILITATOR_URL}/verify"
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            r = await client.post(
                url,
                json={"payment_header": payment_header},
                headers={"Authorization": f"Bearer {settings.COINBASE_CDP_KEY}"},
            )
            return bool(r.json().get("verified"))
        except (httpx.HTTPError, json.JSONDecodeError) as e:
            log.error("x402_facilitator_failed", error=str(e))
            return False


def require_payment(price: PriceConfig, recipient_lookup: Optional[Callable[[], str]] = None) -> Callable:
    """
    FastAPI dependency factory.

    Usage:
        @app.get("/signal", dependencies=[Depends(require_payment(PriceConfig(usdc=0.50)))])
        async def get_signal():
            ...
    """
    settings = get_settings()

    async def dependency(request: Request, x_payment: Optional[str] = Header(default=None)):
        recipient = price.recipient_addr or (recipient_lookup() if recipient_lookup else "")
        if not recipient:
            log.error("x402_no_recipient_configured")
            raise HTTPException(status_code=500, detail="recipient address not configured")

        # 402 with payment requirements if header missing
        if not x_payment:
            log.info("x402_payment_required", path=request.url.path, price_usdc=price.usdc)
            return _build_402_response(price, recipient)

        # MOCK_MODE: any non-empty header passes, no facilitator call
        if settings.MOCK_MODE:
            log.info("x402_mock_accepted", path=request.url.path, payer_token=x_payment[:16] + "...")
            return None  # OK to proceed

        # Demo bypass: configured token skips CDP facilitator for demo/judging
        if settings.X402_DEMO_TOKEN and x_payment == settings.X402_DEMO_TOKEN:
            log.info("x402_demo_token_accepted", path=request.url.path)
            return None

        # Real mode: ask facilitator
        verified = await _verify_with_facilitator(x_payment)
        if not verified:
            log.warning("x402_payment_invalid", path=request.url.path)
            raise HTTPException(status_code=402, detail="payment invalid")

        log.info("x402_payment_verified", path=request.url.path)
        return None

    return dependency
