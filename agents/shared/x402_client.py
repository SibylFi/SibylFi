"""
x402 client for the Trading Agent.

Per the x402-and-uniswap skill, the Python `pip install x402` package is alpha
and post-cutoff for most models. We use httpx + a hand-rolled signature flow
in MOCK_MODE, and shell out to a Node helper for real x402 transactions.

In MOCK_MODE, payments are simulated — the X-PAYMENT header is a JWT-style
token containing payer/recipient/amount, and the server middleware accepts
any non-empty header. This is enough for end-to-end pipeline testing.
"""
from __future__ import annotations

import base64
import json
import secrets
from dataclasses import dataclass
from typing import Any, Optional

import httpx
import structlog

from .settings import get_settings

log = structlog.get_logger(__name__)


@dataclass
class PaymentDetails:
    asset: str
    amount: str
    pay_to: str
    network: str


@dataclass
class PaidResponse:
    """The signal/risk attestation returned after payment."""
    body: Any
    payment_token: str  # the X-PAYMENT header we sent (for receipts)


async def fetch_paywalled(
    url: str,
    *,
    payer_addr: str,
    payer_priv_key: str,
    method: str = "GET",
    json_body: Optional[dict] = None,
    max_pay_usdc: float = 5.0,
) -> PaidResponse:
    """
    Two-shot x402 fetch: first request gets 402 with payment details, second
    request includes the X-PAYMENT header.

    In MOCK_MODE, the X-PAYMENT header is a base64'd JSON blob the mock
    middleware accepts. In real mode, this would shell out to a Node helper
    around `@coinbase/x402-fetch`.
    """
    settings = get_settings()

    async with httpx.AsyncClient(timeout=15.0) as client:
        # First shot — expect 402 (payment required) or 204 (no signal this bar)
        first = await client.request(method, url, json=json_body)
        if first.status_code == 200:
            # Paywall middleware let it through — return what we got
            log.info("x402_first_shot_200_no_charge", url=url)
            return PaidResponse(body=first.json(), payment_token="")

        if first.status_code == 204:
            # Research agent produced no signal — nothing to buy, no charge
            log.info("x402_no_signal_this_bar", url=url)
            return PaidResponse(body=None, payment_token="")

        if first.status_code != 402:
            raise RuntimeError(f"unexpected status {first.status_code}: {first.text}")

        details = first.json()
        accepts = details.get("accepts", [])
        if not accepts:
            raise RuntimeError("402 response has no `accepts` array")

        accept = accepts[0]
        amount_required = int(accept["max_amount_required"]) / 1_000_000  # USDC has 6 decimals
        if amount_required > max_pay_usdc:
            raise RuntimeError(
                f"price ${amount_required} exceeds max ${max_pay_usdc}"
            )

        payment = PaymentDetails(
            asset=accept["asset"],
            amount=accept["max_amount_required"],
            pay_to=accept["pay_to"],
            network=accept["network"],
        )

        # Build the X-PAYMENT header
        if settings.MOCK_MODE:
            payment_header = _mock_x402_header(
                payer=payer_addr, payment=payment
            )
        elif settings.X402_DEMO_TOKEN:
            # Demo mode: use the configured bypass token so the full pipeline
            # runs without a live CDP subscription.
            payment_header = settings.X402_DEMO_TOKEN
        else:
            payment_header = await _real_x402_header(
                payer_priv_key=payer_priv_key, payment=payment
            )

        # Second shot — with payment
        second = await client.request(
            method, url,
            json=json_body,
            headers={"X-PAYMENT": payment_header},
        )
        if second.status_code == 204:
            # Research agent accepted payment but produced no signal this bar.
            return PaidResponse(body=None, payment_token=payment_header)
        if second.status_code != 200:
            raise RuntimeError(
                f"paid request failed: {second.status_code} {second.text}"
            )

        return PaidResponse(body=second.json(), payment_token=payment_header)


def _mock_x402_header(payer: str, payment: PaymentDetails) -> str:
    """
    Mock X-PAYMENT token: base64url JSON. Real x402 uses EIP-3009 transferWithAuthorization
    or a permit flow; we simulate just enough for end-to-end testing.
    """
    blob = {
        "v": 1,
        "scheme": "exact",
        "network": payment.network,
        "payer": payer,
        "pay_to": payment.pay_to,
        "asset": payment.asset,
        "amount": payment.amount,
        "nonce": secrets.token_hex(16),
        "_mock": True,
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps(blob, separators=(",", ":")).encode()
    ).decode().rstrip("=")
    return f"mock.{encoded}"


async def _real_x402_header(payer_priv_key: str, payment: PaymentDetails) -> str:
    """
    Real x402 flow: sign EIP-3009 transferWithAuthorization OR call Node helper
    around @coinbase/x402-fetch.

    For the reference repo we leave this as a placeholder — the recommended
    approach (per the x402-and-uniswap skill) is to shell out to a tiny Node
    script. See tools/x402-client.js (not included in this scaffold).
    """
    raise NotImplementedError(
        "real-mode x402 not implemented in reference scaffold; "
        "set MOCK_MODE=1 or implement Node helper. See "
        ".claude/skills/x402-and-uniswap/SKILL.md for the recommended pattern."
    )
