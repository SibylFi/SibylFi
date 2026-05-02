"""
Uniswap Trading API wrapper.

Per the x402-and-uniswap skill, the `x-universal-router-version: 2.0` header
is silently required and easy to forget. We always include it.

In MOCK_MODE, returns a synthetic quote based on the TWAP fixtures.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx
import structlog

from agents.shared.settings import get_settings

log = structlog.get_logger(__name__)


@dataclass
class Quote:
    quote_id: str
    token_in: str
    token_out: str
    amount_in: str
    amount_out: str
    permit_data: dict           # opaque — pass through to swap unchanged
    expected_slippage_bps: int


@dataclass
class SwapResult:
    tx_hash: str
    actual_fill_price: float
    gas_used: int


class UniswapTradingAPI:
    def __init__(self):
        self.settings = get_settings()
        self.base = self.settings.UNISWAP_TRADING_API_BASE

    async def quote(
        self,
        token_in: str,
        token_out: str,
        amount_in: str,        # smallest unit of token_in
        swapper: str,
    ) -> Quote:
        if self.settings.MOCK_MODE:
            return self._mock_quote(token_in, token_out, amount_in)

        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                f"{self.base}/v1/quote",
                json={
                    "tokenIn": token_in,
                    "tokenOut": token_out,
                    "amount": amount_in,
                    "type": "EXACT_INPUT",
                    "swapper": swapper,
                    "chainId": self.settings.CHAIN_ID_BASE_SEPOLIA,
                },
                headers={
                    "x-api-key": self.settings.UNISWAP_API_KEY,
                    "x-universal-router-version": "2.0",  # silently required
                    "content-type": "application/json",
                },
            )
            r.raise_for_status()
            body = r.json()

        return Quote(
            quote_id=body.get("quoteId", ""),
            token_in=token_in,
            token_out=token_out,
            amount_in=amount_in,
            amount_out=body["amountOut"],
            permit_data=body["permitData"],          # PASS THROUGH UNCHANGED
            expected_slippage_bps=body.get("slippageBps", 0),
        )

    async def swap(self, quote: Quote, signature: str) -> SwapResult:
        if self.settings.MOCK_MODE:
            return self._mock_swap(quote)

        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(
                f"{self.base}/v1/swap",
                json={
                    "quote": {
                        "quoteId": quote.quote_id,
                        "amount": quote.amount_in,
                        "amountOut": quote.amount_out,
                    },
                    "permitData": quote.permit_data,    # MUST be unchanged
                    "signature": signature,
                },
                headers={
                    "x-api-key": self.settings.UNISWAP_API_KEY,
                    "x-universal-router-version": "2.0",
                    "content-type": "application/json",
                },
            )
            r.raise_for_status()
            body = r.json()

        return SwapResult(
            tx_hash=body["txHash"],
            actual_fill_price=float(body["filledPrice"]),
            gas_used=int(body["gasUsed"]),
        )

    # ─────────────────────────────────────────────────────────────────
    # Mocks
    # ─────────────────────────────────────────────────────────────────

    def _mock_quote(self, token_in: str, token_out: str, amount_in: str) -> Quote:
        return Quote(
            quote_id="mock-quote-" + amount_in[:6],
            token_in=token_in,
            token_out=token_out,
            amount_in=amount_in,
            amount_out=str(int(int(amount_in) * 0.997)),  # 0.3% mock spread
            permit_data={"_mock": True, "domain": {}, "types": {}, "values": {}},
            expected_slippage_bps=8,
        )

    def _mock_swap(self, quote: Quote) -> SwapResult:
        from secrets import token_hex
        return SwapResult(
            tx_hash="0x" + token_hex(32),
            actual_fill_price=1.0,  # Trading Agent computes real fill price separately
            gas_used=180_000,
        )
