"""
Trading Agent.

For a given (token, capital), this agent:
  1. Discovers Research Agents via ERC-8004 IdentityRegistry
  2. Ranks them by reputation
  3. Buys the top-ranked agent's signal via x402
  4. Calls Risk Agent to verify the signal (also via x402)
  5. If risk passes, executes a swap on Uniswap Trading API
  6. Records the execution in Postgres for the Validator to settle later
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import structlog
from eth_account import Account

from agents.shared.db import db_conn
from agents.shared.erc8004_client import ERC8004Client, AgentRecord
from agents.shared.settings import get_settings
from agents.shared.signal_schema import RiskAttestation, Signal
from agents.shared.signing import verify_signal
from agents.shared.x402_client import fetch_paywalled
from agents.trading.uniswap import (
    MainnetReferenceQuote,
    Quote,
    SwapResult,
    UniswapTradingAPI,
)

log = structlog.get_logger(__name__)


@dataclass
class TradeResult:
    signal: Signal | None
    risk: RiskAttestation | None
    quote: Quote | None
    swap: SwapResult | None
    mainnet_reference: MainnetReferenceQuote | None = None
    skipped_reason: str | None = None


class TradingAgent:
    def __init__(self):
        self.settings = get_settings()
        self.priv_key = self.settings.TRADING_KEY
        self.address = Account.from_key(self.priv_key).address
        self.erc8004 = ERC8004Client()
        self.uniswap = UniswapTradingAPI()

    async def discover_and_trade(
        self,
        token: str = "WETH/USDC",
        capital_usd: float = 1000.0,
        publisher_ens: str | None = None,
    ) -> TradeResult:
        """The full pipeline.

        publisher_ens: when set, force the trade through this specific
        Research Agent instead of auto-ranking by reputation. Lets the UI
        let users pick swing vs scalper rather than always defaulting to
        whichever has higher score.
        """

        # 1. Discover Research Agents
        agents = self.erc8004.list_agents()
        if publisher_ens:
            chosen = next(
                (a for a in agents if a.ens_name.lower() == publisher_ens.lower()),
                None,
            )
            if chosen is None:
                raise RuntimeError(
                    f"publisher_ens={publisher_ens!r} not found among "
                    f"{[a.ens_name for a in agents]}"
                )
        else:
            ranked = sorted(
                agents,
                key=lambda a: self.erc8004.get_reputation_score(a.agent_id),
                reverse=True,
            )
            if not ranked:
                raise RuntimeError("no Research Agents registered")
            chosen = ranked[0]
        log.info("trading_chose_publisher", ens=chosen.ens_name, agent_id=chosen.agent_id)

        # 2. Pay for and fetch the signal
        signal = await self._buy_signal(chosen, token=token)

        if signal is None:
            log.info("trading_no_signal_this_bar", ens=chosen.ens_name)
            return TradeResult(signal=None, risk=None, quote=None, swap=None,
                               skipped_reason="research_agent_no_signal")

        # 3. Verify signature locally (defense-in-depth before paying for risk check)
        if not verify_signal(signal, chosen.owner):
            raise RuntimeError("signal signature mismatch — refusing to act")

        # 4. Risk check
        risk = await self._call_risk_agent(
            signal=signal,
            capital_usd=capital_usd,
            publisher_addr=chosen.owner,
        )

        if not risk.pass_:
            log.warning("risk_failed_skipping_trade", failed=[c.value for c in risk.failed_checks])
            return TradeResult(signal=signal, risk=risk, quote=None, swap=None,
                              skipped_reason=f"risk_failed: {[c.value for c in risk.failed_checks]}")

        # 5. Execute on Uniswap (Base Sepolia, V3 SwapRouter02 direct).
        amount_in_usdc_micro = str(int(capital_usd * 1_000_000))   # USDC has 6 decimals
        quote = await self.uniswap.quote(
            token_in=self.settings.USDC_BASE_SEPOLIA,
            token_out=self.settings.WETH_BASE_SEPOLIA,
            amount_in=amount_in_usdc_micro,
            swapper=self.address,
        )
        # Pull a mainnet reference quote in parallel — demo-only price oracle,
        # never gates execution. Logged regardless of testnet outcome.
        ref = await self.uniswap.mainnet_reference_quote(
            amount_in_usdc_micro=amount_in_usdc_micro,
            swapper=self.address,
        )
        swap = await self.uniswap.swap(quote=quote)

        # 6. Record execution
        await self._record_execution(signal, capital_usd, quote, swap)

        return TradeResult(signal=signal, risk=risk, quote=quote, swap=swap, mainnet_reference=ref)

    # ─────────────────────────────────────────────────────────────────

    async def _buy_signal(self, agent: AgentRecord, token: str) -> Signal | None:
        url = f"{agent.endpoint}?token={token}"
        result = await fetch_paywalled(
            url=url,
            payer_addr=self.address,
            payer_priv_key=self.priv_key,
            method="GET",
        )
        if result.body is None:
            return None  # research agent had no signal this bar
        return Signal(**result.body)

    async def _call_risk_agent(
        self,
        signal: Signal,
        capital_usd: float,
        publisher_addr: str,
    ) -> RiskAttestation:
        url = "http://risk-agent:7105/verify"
        result = await fetch_paywalled(
            url=url,
            payer_addr=self.address,
            payer_priv_key=self.priv_key,
            method="POST",
            json_body={
                "signal": signal.model_dump(),
                "capital_usd": capital_usd,
                "buyer_addr": self.address,
                "publisher_addr": publisher_addr,
            },
        )
        return RiskAttestation(**result.body)

    async def _record_execution(
        self,
        signal: Signal,
        capital_usd: float,
        quote: Quote,
        swap: SwapResult,
    ) -> None:
        # Use the on-chain fill amount from the receipt when present, otherwise
        # fall back to the quoted amount. Both are smallest-unit ints.
        amount_in_usdc = int(quote.amount_in) / 1_000_000
        amount_out_raw = int(swap.amount_out) if swap.amount_out else int(quote.amount_out)
        amount_out_token = amount_out_raw / 1e18  # WETH is 18-decimal
        actual_fill = amount_in_usdc / amount_out_token if amount_out_token > 0 else 0.0

        async with db_conn() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO executions (
                        signal_id, buyer_addr, capital_usd,
                        actual_fill_price, twap_at_execution, gas_used, tx_hash
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        signal.signal_id,
                        self.address,
                        capital_usd,
                        actual_fill,
                        signal.entry_condition.reference_price,  # mock TWAP-at-execution
                        swap.gas_used,
                        swap.tx_hash,
                    ),
                )
            await conn.commit()
        log.info("execution_recorded", signal_id=signal.signal_id, tx=swap.tx_hash)
