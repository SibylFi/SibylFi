"""
Base Research Agent.

Each persona (mean-rev, momentum, news-driven) inherits from this. The
persona-specific code is tiny — just the prompt and the reference-price
selection logic. Everything else (signing, x402 paywall, persistence) is
shared.
"""
from __future__ import annotations

import re
import secrets
from dataclasses import dataclass

import structlog
from eth_account import Account

from agents.shared.db import db_conn
from agents.shared.inference import infer
from agents.shared.settings import get_settings
from agents.shared.signal_schema import EntryCondition, Signal
from agents.shared.signing import sign_signal

log = structlog.get_logger(__name__)


@dataclass
class PersonaConfig:
    name: str            # e.g., "meanrev"
    ens_name: str        # e.g., "reversal.sibyl.eth"
    private_key: str
    price_per_signal_usdc: float
    prompt_template: str
    horizon_seconds: int


class BaseResearchAgent:
    def __init__(self, persona: PersonaConfig):
        self.persona = persona
        self.settings = get_settings()
        self.address = Account.from_key(persona.private_key).address

    async def generate_signal(
        self,
        token: str,
        reference_price: float,
        published_at_block: int,
    ) -> Signal:
        """Run inference, parse the response, build a signed Signal."""

        prompt = self.persona.prompt_template.format(
            token=token,
            reference_price=reference_price,
        )
        result = await infer(prompt, persona=self.persona.name, max_tokens=256)

        direction, confidence_bps = _parse_inference(result.text)

        # Compute target/stop prices from direction and confidence
        target_pct = _confidence_to_target_pct(confidence_bps)
        if direction == "long":
            target_price = reference_price * (1 + target_pct)
            stop_price = reference_price * (1 - target_pct * 0.6)  # tighter stop than target
        else:
            target_price = reference_price * (1 - target_pct)
            stop_price = reference_price * (1 + target_pct * 0.6)

        signal_id = "0x" + secrets.token_hex(32)

        unsigned = Signal(
            signal_id=signal_id,
            publisher=self.persona.ens_name,
            token=token,
            direction=direction,
            entry_condition=EntryCondition(
                type="market_at_publication",
                reference_price=reference_price,
            ),
            target_price=round(target_price, 4),
            stop_price=round(stop_price, 4),
            horizon_seconds=self.persona.horizon_seconds,
            confidence_bps=confidence_bps,
            published_at_block=published_at_block,
            signature="0x00",  # placeholder; replaced below
        )

        # Sign and stamp
        sig_hex = sign_signal(unsigned, self.persona.private_key)
        signed = unsigned.model_copy(update={"signature": sig_hex})

        log.info(
            "signal_generated",
            signal_id=signal_id,
            persona=self.persona.name,
            direction=direction,
            confidence_bps=confidence_bps,
            target=signed.target_price,
            backend=result.backend,
        )

        await self._persist(signed)
        return signed

    async def _persist(self, signal: Signal) -> None:
        """Write signal to Postgres signal log."""
        async with db_conn() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO signals (
                        signal_id, publisher, publisher_addr, token, direction,
                        reference_price, target_price, stop_price,
                        horizon_seconds, confidence_bps,
                        horizon_expires_at, raw_payload
                    ) VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s, %s,
                        %s, %s,
                        NOW() + (%s || ' seconds')::interval,
                        %s
                    )
                    ON CONFLICT (signal_id) DO NOTHING
                    """,
                    (
                        signal.signal_id, signal.publisher, self.address,
                        signal.token, signal.direction,
                        signal.entry_condition.reference_price,
                        signal.target_price, signal.stop_price,
                        signal.horizon_seconds, signal.confidence_bps,
                        signal.horizon_seconds,
                        signal.model_dump_json(),
                    ),
                )
            await conn.commit()


# ─────────────────────────────────────────────────────────────────────────
# Inference parsing
# ─────────────────────────────────────────────────────────────────────────

_DIRECTION_RE = re.compile(r"DIRECTION:\s*(LONG|SHORT)", re.IGNORECASE)
_CONFIDENCE_RE = re.compile(r"CONFIDENCE_BPS:\s*(\d{1,5})", re.IGNORECASE)


def _parse_inference(text: str) -> tuple[str, int]:
    """Extract direction and confidence_bps from the model's response text."""
    direction_match = _DIRECTION_RE.search(text)
    confidence_match = _CONFIDENCE_RE.search(text)

    direction = (direction_match.group(1).lower() if direction_match else "long")
    if direction not in ("long", "short"):
        direction = "long"

    confidence_bps = int(confidence_match.group(1)) if confidence_match else 5500
    confidence_bps = max(0, min(10000, confidence_bps))

    return direction, confidence_bps


def _confidence_to_target_pct(confidence_bps: int) -> float:
    """
    Higher confidence → larger target. Capped so targets stay realistic.

    confidence_bps 5000 (50%) → 0.4% target
    confidence_bps 7000 (70%) → 0.8% target
    confidence_bps 9000 (90%) → 1.4% target
    """
    pct = 0.001 + (confidence_bps - 5000) / 5000 * 0.012  # linear from 0.1% to 1.4%
    return max(0.001, min(0.025, pct))
