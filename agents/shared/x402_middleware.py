"""
x402 server middleware for SibylFi paid endpoints.

Drop this dependency on any FastAPI route to require a micropayment:

    from agents.shared.x402_middleware import require_payment, PriceConfig

    @app.get("/signal", dependencies=[Depends(require_payment(PriceConfig(usdc=0.50)))])
    async def get_signal():
        ...

Wire shape (canonical x402 v1):

  402 body                                   →  paymentRequirements (camelCase)
  client base64(payload)                     →  X-PAYMENT header
  facilitator.verify({payload, requirements}) → settle on success

In MOCK_MODE, the dependency accepts any non-empty X-PAYMENT header and skips
facilitator verification. With FORCE_X402_DEMO=1, the configured DEMO token is
also accepted — useful when running in real-mode RPC but without faucet USDC
to test the whole loop. Outside those two escape hatches, every call goes
through the public facilitator on https://facilitator.x402.rs.
"""
import base64
import json
from dataclasses import dataclass
from typing import Callable, Optional

import httpx
import structlog
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from .settings import get_settings

log = structlog.get_logger(__name__)


@dataclass
class PriceConfig:
    """Per-endpoint pricing configuration."""
    usdc: float                              # price in USDC (will be converted to 6-decimal int)
    description: str = ""
    recipient_addr: str = ""                 # if empty, looked up via recipient_lookup
    network: str = ""                        # default settings.X402_NETWORK
    max_timeout_seconds: int = 300

    def usdc_micro_amount(self) -> int:
        """Returns price in USDC's smallest unit (USDC has 6 decimals)."""
        return int(self.usdc * 1_000_000)


def _payment_requirements(price: PriceConfig, recipient: str, resource_url: str) -> dict:
    """Canonical x402 PaymentRequirements (camelCase, with USDC EIP-712 domain)."""
    settings = get_settings()
    return {
        "scheme": "exact",
        "network": price.network or settings.X402_NETWORK,
        "maxAmountRequired": str(price.usdc_micro_amount()),
        "resource": resource_url,
        "description": price.description,
        "mimeType": "application/json",
        "payTo": recipient,
        "maxTimeoutSeconds": price.max_timeout_seconds,
        "asset": settings.USDC_BASE_SEPOLIA,
        "extra": {
            # Required for the payer to compute USDC's EIP-712 domain separator.
            # USDC on Base Sepolia uses name="USDC", version="2".
            "name": "USDC",
            "version": "2",
        },
    }


class Payment402Required(Exception):
    """Raised by require_payment to short-circuit a route. The matching
    exception handler (installed via install_x402_handlers) converts it to a
    canonical x402 v1 body — `{x402Version, accepts: [...]}` at top level."""
    def __init__(self, body: dict):
        self.body = body
        super().__init__("payment required")


def _raise_402(price: PriceConfig, recipient: str, resource_url: str) -> None:
    body = {
        "x402Version": 1,
        "accepts": [_payment_requirements(price, recipient, resource_url)],
    }
    raise Payment402Required(body)


def install_x402_handlers(app: FastAPI) -> None:
    """Register the Payment402Required exception handler so the canonical x402
    body is emitted at top level (not nested under FastAPI's `detail`)."""
    @app.exception_handler(Payment402Required)
    async def _on_402(_request: Request, exc: Payment402Required):
        return JSONResponse(status_code=402, content=exc.body)


def _decode_payment_header(header: str) -> Optional[dict]:
    """Decode the base64url-encoded X-PAYMENT header to a dict, or None on garbage."""
    try:
        # x402 spec is base64url with optional padding stripping.
        pad = "=" * (-len(header) % 4)
        return json.loads(base64.urlsafe_b64decode(header + pad).decode())
    except Exception:
        return None


async def _facilitator_call(path: str, body: dict) -> dict:
    settings = get_settings()
    url = f"{settings.X402_FACILITATOR_URL}{path}"
    headers = {"content-type": "application/json"}
    # Public testnet facilitator (x402.rs) needs no auth. CDP-hosted mainnet
    # facilitator wants a bearer token — pass it through if configured.
    if settings.COINBASE_CDP_KEY:
        headers["Authorization"] = f"Bearer {settings.COINBASE_CDP_KEY}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(url, json=body, headers=headers)
        try:
            return {"status": r.status_code, **r.json()}
        except json.JSONDecodeError:
            return {"status": r.status_code, "raw": r.text}


def require_payment(price: PriceConfig, recipient_lookup: Optional[Callable[[], str]] = None) -> Callable:
    """
    FastAPI dependency factory.

    Usage:
        @app.get("/signal", dependencies=[Depends(require_payment(PriceConfig(usdc=0.50)))])
        async def get_signal():
            ...
    """

    async def dependency(request: Request, x_payment: Optional[str] = Header(default=None)):
        settings = get_settings()
        recipient = price.recipient_addr or (recipient_lookup() if recipient_lookup else "")
        if not recipient:
            log.error("x402_no_recipient_configured")
            raise HTTPException(status_code=500, detail="recipient address not configured")

        resource_url = str(request.url)

        # 402 with payment requirements if header missing
        if not x_payment:
            log.info("x402_payment_required", path=request.url.path, price_usdc=price.usdc)
            _raise_402(price, recipient, resource_url)

        # MOCK_MODE: any non-empty header passes (offline pipeline tests).
        if settings.MOCK_MODE:
            log.info("x402_mock_accepted", path=request.url.path)
            return None

        # Demo bypass: only when explicitly enabled. Never silent in real mode.
        if settings.FORCE_X402_DEMO and settings.X402_DEMO_TOKEN and x_payment == settings.X402_DEMO_TOKEN:
            log.info("x402_demo_token_accepted", path=request.url.path)
            return None

        # Real path: ask the facilitator to verify, then settle.
        decoded_payload = _decode_payment_header(x_payment)
        if decoded_payload is None:
            log.warning("x402_payment_header_unparseable", path=request.url.path)
            raise HTTPException(status_code=402, detail="X-PAYMENT not parseable")

        requirements = _payment_requirements(price, recipient, resource_url)
        # x402-rs facilitator wants x402Version at the TOP level of /verify and
        # /settle bodies, not nested under paymentPayload only. Without it the
        # facilitator fails fast with `unsupported_scheme` before signature
        # checks even start.
        body = {
            "x402Version":         1,
            "paymentPayload":      decoded_payload,
            "paymentRequirements": requirements,
        }
        verify = await _facilitator_call("/verify", body)
        if not verify.get("isValid"):
            log.warning(
                "x402_payment_invalid",
                path=request.url.path,
                reason=verify.get("invalidReason"),
                detail=verify.get("invalidReasonDetails"),
            )
            raise HTTPException(status_code=402, detail=f"payment invalid: {verify.get('invalidReason')}")

        settle = await _facilitator_call("/settle", body)
        if not settle.get("success", False):
            log.warning(
                "x402_settle_failed",
                path=request.url.path,
                error=settle.get("errorReason") or settle.get("error"),
            )
            raise HTTPException(status_code=402, detail="payment settlement failed")

        log.info(
            "x402_payment_settled",
            path=request.url.path,
            tx=settle.get("transaction"),
            payer=settle.get("payer"),
        )
        # Bubble settlement metadata back to the caller via response headers.
        request.state.x402_settle = settle
        return None

    return dependency
