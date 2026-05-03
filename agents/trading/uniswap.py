"""
On-chain Uniswap V3 swap client.

Uniswap's hosted Trading API does not support testnets — quoting USDC/WETH on
Base Sepolia returns ResourceNotFound — so the Trading Agent calls the V3
QuoterV2 + SwapRouter02 directly.

Flow:
  1. QuoterV2.quoteExactInputSingle → expected amountOut
  2. ERC20.allowance → if low, ERC20.approve SwapRouter02 (one-time, big amount)
  3. SwapRouter02.exactInputSingle → broadcast, wait for receipt
  4. Read amountOut from logs and report real fill price

In MOCK_MODE the call is short-circuited to a synthetic Quote/SwapResult so
the orchestrator's offline tests can run end-to-end.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

import httpx
import structlog
from eth_account import Account
from web3 import Web3

from agents.shared.settings import get_settings

log = structlog.get_logger(__name__)


# Minimal ABIs — only the methods we call. Keeping these inline avoids pulling
# the full Uniswap V3 artifacts into the agent image.
_QUOTER_V2_ABI = [
    {
        "name": "quoteExactInputSingle",
        "type": "function",
        "stateMutability": "nonpayable",   # QuoterV2 mutates internal state but is safe to .call()
        "inputs": [{
            "name": "params",
            "type": "tuple",
            "components": [
                {"name": "tokenIn",          "type": "address"},
                {"name": "tokenOut",         "type": "address"},
                {"name": "amountIn",         "type": "uint256"},
                {"name": "fee",              "type": "uint24"},
                {"name": "sqrtPriceLimitX96","type": "uint160"},
            ],
        }],
        "outputs": [
            {"name": "amountOut",                    "type": "uint256"},
            {"name": "sqrtPriceX96After",            "type": "uint160"},
            {"name": "initializedTicksCrossed",      "type": "uint32"},
            {"name": "gasEstimate",                  "type": "uint256"},
        ],
    },
]

_SWAP_ROUTER02_ABI = [
    {
        "name": "exactInputSingle",
        "type": "function",
        "stateMutability": "payable",
        "inputs": [{
            "name": "params",
            "type": "tuple",
            "components": [
                {"name": "tokenIn",            "type": "address"},
                {"name": "tokenOut",           "type": "address"},
                {"name": "fee",                "type": "uint24"},
                {"name": "recipient",          "type": "address"},
                {"name": "amountIn",           "type": "uint256"},
                {"name": "amountOutMinimum",   "type": "uint256"},
                {"name": "sqrtPriceLimitX96",  "type": "uint160"},
            ],
        }],
        "outputs": [{"name": "amountOut", "type": "uint256"}],
    },
]

_ERC20_ABI = [
    {"name": "allowance", "type": "function", "stateMutability": "view",
     "inputs": [{"name": "owner", "type": "address"}, {"name": "spender", "type": "address"}],
     "outputs": [{"name": "", "type": "uint256"}]},
    {"name": "approve", "type": "function", "stateMutability": "nonpayable",
     "inputs": [{"name": "spender", "type": "address"}, {"name": "amount", "type": "uint256"}],
     "outputs": [{"name": "", "type": "bool"}]},
    {"name": "balanceOf", "type": "function", "stateMutability": "view",
     "inputs": [{"name": "owner", "type": "address"}],
     "outputs": [{"name": "", "type": "uint256"}]},
    {"name": "decimals", "type": "function", "stateMutability": "view",
     "inputs": [], "outputs": [{"name": "", "type": "uint8"}]},
]

_MAX_UINT256 = (1 << 256) - 1


@dataclass
class Quote:
    quote_id: str
    token_in: str
    token_out: str
    amount_in: str
    amount_out: str
    fee_tier: int
    expected_slippage_bps: int
    quoted_at: int             # unix seconds — pre-broadcast freshness check


@dataclass
class SwapResult:
    tx_hash: str
    actual_fill_price: float    # token_out per token_in, decimal-adjusted
    gas_used: int
    amount_out: str             # actual amount, smallest unit


@dataclass
class MainnetReferenceQuote:
    """
    Read-only Trading API quote pulled from Ethereum mainnet for *the same pair*
    we're swapping on testnet. Purely a reference-price oracle for the demo —
    nothing here is broadcast. Lets the judge see a live `POST /v1/quote` against
    Uniswap's hosted Trading API alongside the testnet execution.
    """
    quote_id: str
    route: str                   # e.g. "CLASSIC", "DUTCH_V3"
    amount_in: str
    amount_out: str
    block_number: int
    requested_at: int


class UniswapTradingAPI:
    def __init__(self):
        self.settings = get_settings()
        self._w3: Optional[Web3] = None
        self._signer = None

        if not self.settings.MOCK_MODE:
            self._w3 = Web3(Web3.HTTPProvider(self.settings.BASE_SEPOLIA_RPC))
            self._signer = Account.from_key(self.settings.TRADING_KEY)
            self._quoter = self._w3.eth.contract(
                address=Web3.to_checksum_address(self.settings.UNISWAP_V3_QUOTER_V2_BASE_SEPOLIA),
                abi=_QUOTER_V2_ABI,
            )
            self._router = self._w3.eth.contract(
                address=Web3.to_checksum_address(self.settings.UNISWAP_V3_SWAP_ROUTER02_BASE_SEPOLIA),
                abi=_SWAP_ROUTER02_ABI,
            )

    async def quote(
        self,
        token_in: str,
        token_out: str,
        amount_in: str,        # smallest unit of token_in
        swapper: str,          # accepted for parity with Trading API; unused on-chain
    ) -> Quote:
        if self.settings.MOCK_MODE:
            return self._mock_quote(token_in, token_out, amount_in)

        fee = self.settings.UNISWAP_V3_FEE_TIER
        params = (
            Web3.to_checksum_address(token_in),
            Web3.to_checksum_address(token_out),
            int(amount_in),
            fee,
            0,
        )
        # QuoterV2.quoteExactInputSingle is nonpayable but read-only — call() works.
        amount_out, sqrt_after, ticks_crossed, gas_estimate = (
            self._quoter.functions.quoteExactInputSingle(params).call()
        )
        log.info(
            "uniswap_quote",
            token_in=token_in,
            token_out=token_out,
            amount_in=amount_in,
            amount_out=str(amount_out),
            fee=fee,
            ticks_crossed=ticks_crossed,
        )
        return Quote(
            quote_id=f"v3-{int(time.time())}",
            token_in=token_in,
            token_out=token_out,
            amount_in=amount_in,
            amount_out=str(amount_out),
            fee_tier=fee,
            expected_slippage_bps=self.settings.SWAP_SLIPPAGE_BPS,
            quoted_at=int(time.time()),
        )

    async def mainnet_reference_quote(
        self,
        amount_in_usdc_micro: str,
        swapper: str,
    ) -> Optional[MainnetReferenceQuote]:
        """
        Read-only call to Uniswap's hosted Trading API for the SAME pair on
        Ethereum mainnet. Demo surface only — nothing is broadcast. Returns
        None on any failure so a flaky API call never blocks an on-chain swap.
        """
        if self.settings.MOCK_MODE:
            return None
        if not self.settings.UNISWAP_API_KEY or self.settings.UNISWAP_API_KEY.startswith("MOCK"):
            log.info("uniswap_trading_api_skipped_no_key")
            return None

        body = {
            "type":            "EXACT_INPUT",
            "tokenInChainId":  self.settings.CHAIN_ID_ETHEREUM,
            "tokenOutChainId": self.settings.CHAIN_ID_ETHEREUM,
            "tokenIn":         self.settings.USDC_MAINNET,
            "tokenOut":        self.settings.WETH_MAINNET,
            "amount":          amount_in_usdc_micro,
            "swapper":         swapper,
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.post(
                    f"{self.settings.UNISWAP_TRADING_API_BASE}/v1/quote",
                    json=body,
                    headers={
                        "x-api-key": self.settings.UNISWAP_API_KEY,
                        "x-universal-router-version": "2.0",
                        "content-type": "application/json",
                    },
                )
            if r.status_code != 200:
                log.warning(
                    "uniswap_trading_api_non_200",
                    status=r.status_code,
                    body=r.text[:300],
                )
                return None
            payload = r.json()
            # Trading API responses vary by routing type. CLASSIC has
            # `quote.output.amount`, UniswapX variants put it under quote
            # directly. We extract conservatively.
            quote_obj = payload.get("quote") or {}
            amount_out = (
                quote_obj.get("output", {}).get("amount")
                or quote_obj.get("amountOut")
                or "0"
            )
            log.info(
                "uniswap_trading_api_reference_quote",
                routing=payload.get("routing"),
                amount_out=str(amount_out),
                block=quote_obj.get("blockNumber") or quote_obj.get("portionBips"),
            )
            return MainnetReferenceQuote(
                quote_id=payload.get("requestId", ""),
                route=str(payload.get("routing", "")),
                amount_in=amount_in_usdc_micro,
                amount_out=str(amount_out),
                block_number=int(quote_obj.get("blockNumber") or 0),
                requested_at=int(time.time()),
            )
        except (httpx.HTTPError, ValueError) as e:
            log.warning("uniswap_trading_api_error", error=str(e))
            return None

    async def swap(self, quote: Quote, signature: str = "") -> SwapResult:
        """
        Broadcast the swap. `signature` parameter is retained for API parity
        with the Trading API client; on-chain SwapRouter02 doesn't need it
        (no Permit2 — we approve the router up front instead).
        """
        if self.settings.MOCK_MODE:
            return self._mock_swap(quote)

        # ─── Pre-broadcast checks (skill: x402-and-uniswap → "Pre-broadcast checks")
        chain_id = self._w3.eth.chain_id
        if chain_id != self.settings.CHAIN_ID_BASE_SEPOLIA:
            raise RuntimeError(f"connected chain {chain_id} != expected base-sepolia")
        if int(time.time()) - quote.quoted_at > 30:
            raise RuntimeError("quote stale (>30s); refetch before broadcast")
        if int(quote.amount_out) == 0:
            raise RuntimeError("quote.amount_out == 0; pool is empty or route is broken")

        token_in = Web3.to_checksum_address(quote.token_in)
        token_out = Web3.to_checksum_address(quote.token_out)
        router_addr = Web3.to_checksum_address(self.settings.UNISWAP_V3_SWAP_ROUTER02_BASE_SEPOLIA)
        amount_in = int(quote.amount_in)

        erc20 = self._w3.eth.contract(address=token_in, abi=_ERC20_ABI)
        balance = erc20.functions.balanceOf(self._signer.address).call()
        if balance < amount_in:
            raise RuntimeError(
                f"insufficient {token_in} balance: have {balance}, need {amount_in}"
            )

        eth_balance = self._w3.eth.get_balance(self._signer.address)
        if eth_balance < self._w3.to_wei(0.001, "ether"):
            raise RuntimeError(f"insufficient ETH for gas: {eth_balance} wei")

        # ─── Approve once if allowance too low.
        allowance = erc20.functions.allowance(self._signer.address, router_addr).call()
        if allowance < amount_in:
            log.info("uniswap_approving_router", current_allowance=allowance, needed=amount_in)
            self._broadcast_and_wait(
                erc20.functions.approve(router_addr, _MAX_UINT256),
                gas_estimate=80_000,
                tag="approve",
            )

        # ─── Compute amountOutMinimum from slippage tolerance.
        bps = self.settings.SWAP_SLIPPAGE_BPS
        amount_out_min = int(int(quote.amount_out) * (10_000 - bps) // 10_000)

        params = (
            token_in,
            token_out,
            quote.fee_tier,
            self._signer.address,
            amount_in,
            amount_out_min,
            0,           # sqrtPriceLimitX96=0 → no price-limit guardrail (we rely on amountOutMin)
        )

        # Estimate gas with a 30% headroom. The Base Sepolia testnet pool is
        # thinly seeded — gas consumption can balloon past the textbook ~200k
        # if the swap traverses many uninitialised ticks reaching the price
        # limit. eth_estimateGas accounts for that; a static budget does not.
        try:
            estimated = self._w3.eth.estimate_gas({
                "from": self._signer.address,
                "to":   self._router.address,
                "data": self._router.encode_abi("exactInputSingle", args=[params]),
            })
            gas_budget = int(estimated * 13 // 10)
            log.info("uniswap_swap_gas_estimated", estimated=estimated, budget=gas_budget)
        except Exception as e:
            log.warning("uniswap_swap_gas_estimate_failed", error=str(e))
            gas_budget = 1_500_000

        receipt = self._broadcast_and_wait(
            self._router.functions.exactInputSingle(params),
            gas_estimate=gas_budget,
            tag="exactInputSingle",
        )

        # ─── Decode actual amountOut from the Transfer log to token_out → recipient.
        actual_out = _read_transfer_amount(self._w3, receipt, token_out, self._signer.address)
        if actual_out == 0:
            log.warning("uniswap_no_transfer_log_using_quote", tx=receipt["transactionHash"].hex())
            actual_out = int(quote.amount_out)

        # Decimal-adjusted price: token_out per token_in.
        in_decimals = erc20.functions.decimals().call()
        out_decimals = self._w3.eth.contract(address=token_out, abi=_ERC20_ABI).functions.decimals().call()
        price = (actual_out / 10**out_decimals) / (amount_in / 10**in_decimals) if amount_in else 0.0

        log.info(
            "uniswap_swap_executed",
            tx=receipt["transactionHash"].hex(),
            gas=receipt["gasUsed"],
            amount_out=str(actual_out),
            fill_price=price,
        )
        return SwapResult(
            tx_hash=receipt["transactionHash"].hex(),
            actual_fill_price=float(price),
            gas_used=int(receipt["gasUsed"]),
            amount_out=str(actual_out),
        )

    # ─────────────────────────────────────────────────────────────────
    # Internals
    # ─────────────────────────────────────────────────────────────────

    def _broadcast_and_wait(self, fn, gas_estimate: int, tag: str) -> dict:
        """Build → sign → broadcast → wait for receipt. Raises on failed receipts.

        Uses the `pending` block tag for the nonce so back-to-back calls
        (approve → swap) don't collide when the previous tx is mined but the
        node hasn't refreshed its account state yet."""
        nonce = self._w3.eth.get_transaction_count(self._signer.address, "pending")
        tx = fn.build_transaction({
            "from":     self._signer.address,
            "nonce":    nonce,
            "gas":      gas_estimate,
            "maxFeePerGas":         self._w3.to_wei(2, "gwei"),
            "maxPriorityFeePerGas": self._w3.to_wei(1, "gwei"),
            "chainId":  self.settings.CHAIN_ID_BASE_SEPOLIA,
        })
        signed = self._signer.sign_transaction(tx)
        raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
        tx_hash = self._w3.eth.send_raw_transaction(raw)
        log.info(f"uniswap_{tag}_broadcast", tx=tx_hash.hex())
        receipt = self._w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        if receipt["status"] != 1:
            raise RuntimeError(f"{tag} reverted: {tx_hash.hex()}")
        return receipt

    # ─────────────────────────────────────────────────────────────────
    # Mocks (offline)
    # ─────────────────────────────────────────────────────────────────

    def _mock_quote(self, token_in: str, token_out: str, amount_in: str) -> Quote:
        return Quote(
            quote_id="mock-quote-" + amount_in[:6],
            token_in=token_in,
            token_out=token_out,
            amount_in=amount_in,
            amount_out=str(int(int(amount_in) * 0.997)),
            fee_tier=self.settings.UNISWAP_V3_FEE_TIER,
            expected_slippage_bps=8,
            quoted_at=int(time.time()),
        )

    def _mock_swap(self, quote: Quote) -> SwapResult:
        from secrets import token_hex
        return SwapResult(
            tx_hash="0x" + token_hex(32),
            actual_fill_price=1.0,
            gas_used=180_000,
            amount_out=quote.amount_out,
        )


# ─── Log helpers ─────────────────────────────────────────────────────────────

# ERC20 Transfer(address indexed from, address indexed to, uint256 value)
_ERC20_TRANSFER_TOPIC = "0x" + "ddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


def _read_transfer_amount(w3: Web3, receipt: dict, token_addr: str, recipient: str) -> int:
    """Sum Transfer(_, recipient, value) logs on token_addr from the receipt."""
    token_addr = token_addr.lower()
    rec_topic = "0x" + recipient.lower().replace("0x", "").rjust(64, "0")
    total = 0
    for log_entry in receipt.get("logs", []):
        if log_entry["address"].lower() != token_addr:
            continue
        topics = log_entry["topics"]
        if not topics:
            continue
        topic0 = topics[0].hex() if hasattr(topics[0], "hex") else topics[0]
        if not topic0.startswith("0x"):
            topic0 = "0x" + topic0
        if topic0.lower() != _ERC20_TRANSFER_TOPIC:
            continue
        if len(topics) < 3:
            continue
        topic2 = topics[2].hex() if hasattr(topics[2], "hex") else topics[2]
        if not topic2.startswith("0x"):
            topic2 = "0x" + topic2
        if topic2.lower() != rec_topic.lower():
            continue
        data = log_entry["data"]
        if hasattr(data, "hex"):
            data = data.hex()
        if not data.startswith("0x"):
            data = "0x" + data
        total += int(data, 16) if data not in ("0x", "0x0") else 0
    return total
