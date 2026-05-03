"""
x402 client for the Trading Agent.

Real-mode flow (MOCK_MODE=0, FORCE_X402_DEMO=0):
  1. GET/POST resource → server returns 402 + paymentRequirements
  2. Build EIP-3009 transferWithAuthorization typed-data payload
  3. Sign with payer's private key (eth_account.sign_typed_data)
  4. base64url-encode {x402Version, scheme, network, payload}
  5. Repeat the request with X-PAYMENT header — server verifies + settles
     against the public facilitator (https://facilitator.x402.rs by default),
     which broadcasts the USDC transfer to base-sepolia.

In MOCK_MODE the X-PAYMENT header is a tiny base64'd JSON the mock middleware
accepts unconditionally — enough for offline end-to-end tests.
"""
from __future__ import annotations

import base64
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any, Optional

import httpx
import structlog
from eth_account import Account
from eth_account.messages import encode_typed_data

from .settings import get_settings

log = structlog.get_logger(__name__)


@dataclass
class PaymentDetails:
    asset: str
    amount: str
    pay_to: str
    network: str
    extra: dict             # USDC EIP-712 domain hints: {"name", "version"}


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
    Two-shot x402 fetch. The first request gets either a 402 with payment
    details, a 200 (the server let it through), or a 204 (the upstream produced
    no content this bar). On 402, build a signed X-PAYMENT header and replay.
    """
    settings = get_settings()

    async with httpx.AsyncClient(timeout=20.0) as client:
        first = await client.request(method, url, json=json_body)
        if first.status_code == 200:
            log.info("x402_first_shot_200_no_charge", url=url)
            return PaidResponse(body=first.json(), payment_token="")

        if first.status_code == 204:
            log.info("x402_no_signal_this_bar", url=url)
            return PaidResponse(body=None, payment_token="")

        if first.status_code != 402:
            raise RuntimeError(f"unexpected status {first.status_code}: {first.text}")

        details = first.json()
        accepts = details.get("accepts", [])
        if not accepts:
            raise RuntimeError("402 response has no `accepts` array")

        # Take the first acceptable requirement we can satisfy. For SibylFi
        # all paid endpoints announce a single base-sepolia/USDC requirement.
        accept = accepts[0]
        amount_required = int(accept["maxAmountRequired"]) / 1_000_000
        if amount_required > max_pay_usdc:
            raise RuntimeError(f"price ${amount_required} exceeds max ${max_pay_usdc}")

        payment = PaymentDetails(
            asset=accept["asset"],
            amount=accept["maxAmountRequired"],
            pay_to=accept["payTo"],
            network=accept["network"],
            extra=accept.get("extra") or {},
        )

        # Build the X-PAYMENT header.
        if settings.MOCK_MODE:
            payment_header = _mock_x402_header(payer=payer_addr, payment=payment)
        elif settings.FORCE_X402_DEMO and settings.X402_DEMO_TOKEN:
            # Explicit demo bypass — useful when running against real RPC but
            # without a faucet-funded payer wallet.
            payment_header = settings.X402_DEMO_TOKEN
        else:
            payment_header = _build_real_header(
                payer_addr=payer_addr,
                payer_priv_key=payer_priv_key,
                payment=payment,
            )

        second = await client.request(
            method, url,
            json=json_body,
            headers={"X-PAYMENT": payment_header},
        )
        if second.status_code == 204:
            return PaidResponse(body=None, payment_token=payment_header)
        if second.status_code != 200:
            raise RuntimeError(f"paid request failed: {second.status_code} {second.text}")

        return PaidResponse(body=second.json(), payment_token=payment_header)


def _mock_x402_header(payer: str, payment: PaymentDetails) -> str:
    """Tiny base64'd token the mock middleware accepts for offline runs."""
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


def _network_to_chain_id(network: str) -> int:
    """Map x402 network identifier to its EIP-155 chain ID."""
    mapping = {
        "base-sepolia": 84532,
        "base":         8453,
        "ethereum":     1,
        "sepolia":      11155111,
    }
    if network not in mapping:
        raise ValueError(f"unknown x402 network {network!r}")
    return mapping[network]


def _build_real_header(payer_addr: str, payer_priv_key: str, payment: PaymentDetails) -> str:
    """
    Sign EIP-3009 transferWithAuthorization for the USDC contract on the target
    network, then assemble the canonical x402 v1 X-PAYMENT header.
    """
    chain_id = _network_to_chain_id(payment.network)
    name = payment.extra.get("name", "USD Coin")
    version = payment.extra.get("version", "2")

    now = int(time.time())
    valid_after = 0
    valid_before = now + 600           # 10-minute window
    nonce = "0x" + secrets.token_hex(32)

    # Canonical EIP-712 typed data for USDC's transferWithAuthorization.
    typed_data = {
        "types": {
            "EIP712Domain": [
                {"name": "name",              "type": "string"},
                {"name": "version",           "type": "string"},
                {"name": "chainId",           "type": "uint256"},
                {"name": "verifyingContract", "type": "address"},
            ],
            "TransferWithAuthorization": [
                {"name": "from",         "type": "address"},
                {"name": "to",           "type": "address"},
                {"name": "value",        "type": "uint256"},
                {"name": "validAfter",   "type": "uint256"},
                {"name": "validBefore",  "type": "uint256"},
                {"name": "nonce",        "type": "bytes32"},
            ],
        },
        "primaryType": "TransferWithAuthorization",
        "domain": {
            "name":              name,
            "version":           version,
            "chainId":           chain_id,
            "verifyingContract": payment.asset,
        },
        "message": {
            "from":        payer_addr,
            "to":          payment.pay_to,
            "value":       int(payment.amount),
            "validAfter":  valid_after,
            "validBefore": valid_before,
            "nonce":       nonce,
        },
    }

    signable = encode_typed_data(full_message=typed_data)
    signed = Account.sign_message(signable, private_key=payer_priv_key)
    signature = "0x" + signed.signature.hex() if not signed.signature.hex().startswith("0x") else signed.signature.hex()

    payload = {
        "x402Version": 1,
        "scheme":      "exact",
        "network":     payment.network,
        "payload": {
            "signature": signature,
            "authorization": {
                "from":        payer_addr,
                "to":          payment.pay_to,
                "value":       payment.amount,
                "validAfter":  str(valid_after),
                "validBefore": str(valid_before),
                "nonce":       nonce,
            },
        },
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode()
    ).decode().rstrip("=")

    log.info(
        "x402_real_header_built",
        payer=payer_addr,
        pay_to=payment.pay_to,
        amount_usdc=int(payment.amount) / 1_000_000,
        valid_before=valid_before,
    )
    return encoded
