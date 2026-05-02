"""
Canonical signal schema for SibylFi.

Every Research Agent, the Trading Agent, the Risk Agent, the Validator Agent,
and the orchestrator parse signals against this exact model. Drift here breaks
the whole pipeline silently — see signal-validator-spec skill in .claude/skills/.

The schema mirrors specs/signal-validator.md. When updating one, update both.
"""
from __future__ import annotations

import hashlib
import json
from enum import Enum
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, Field, field_validator


# ─────────────────────────────────────────────────────────────────────────
# Type aliases
# ─────────────────────────────────────────────────────────────────────────

Direction = Literal["long", "short"]
Hex32 = Annotated[str, Field(pattern=r"^0x[0-9a-fA-F]{64}$")]
HexSig = Annotated[str, Field(pattern=r"^0x[0-9a-fA-F]+$")]
EnsName = Annotated[str, Field(pattern=r"^[a-z0-9-]+\.sibyl\.eth$")]


# ─────────────────────────────────────────────────────────────────────────
# Entry condition (extension point — only one type supported in v1)
# ─────────────────────────────────────────────────────────────────────────

class EntryCondition(BaseModel):
    type: Literal["market_at_publication"] = "market_at_publication"
    reference_price: float

    @field_validator("reference_price")
    @classmethod
    def _positive_price(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("reference_price must be positive")
        return v


# ─────────────────────────────────────────────────────────────────────────
# Signal — the canonical wire format
# ─────────────────────────────────────────────────────────────────────────

class Signal(BaseModel):
    """
    A signed trading signal. The signature covers the canonicalized JSON of
    every other field — see canonicalize() and verify_signature().
    """
    signal_id: Hex32
    publisher: EnsName
    token: str  # CAIP-19 token identifier, e.g. eip155:84532/erc20:0x...
    direction: Direction
    entry_condition: EntryCondition
    target_price: float
    stop_price: float
    horizon_seconds: int = Field(ge=900, le=86400)  # 15min to 24h
    confidence_bps: int = Field(ge=0, le=10000)
    published_at_block: int
    signature: HexSig

    @field_validator("target_price", "stop_price")
    @classmethod
    def _positive_price(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("price must be positive")
        return v

    def canonicalize(self) -> bytes:
        """Canonical bytes for signing/verification (signature field excluded, keys sorted)."""
        body = self.model_dump(exclude={"signature"})
        return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def hash(self) -> bytes:
        return hashlib.sha256(self.canonicalize()).digest()


# ─────────────────────────────────────────────────────────────────────────
# Risk attestation
# ─────────────────────────────────────────────────────────────────────────

class RiskCheck(str, Enum):
    POSITION_SIZE = "position_size"
    SLIPPAGE = "slippage"
    VOLATILITY = "volatility"
    LIQUIDITY = "liquidity"
    SELF_PURCHASE = "self_purchase"


class RiskAttestation(BaseModel):
    """Risk Agent's signed attestation that a signal passes deterministic checks."""
    signal_id: Hex32
    pass_: bool = Field(alias="pass")
    failed_checks: list[RiskCheck] = Field(default_factory=list)
    expected_slippage_bps: int
    pool_tvl_usd: float
    risk_attester: str  # ENS or address
    signature: HexSig

    model_config = {"populate_by_name": True}


# ─────────────────────────────────────────────────────────────────────────
# Settlement record (what the Validator writes)
# ─────────────────────────────────────────────────────────────────────────

class Outcome(str, Enum):
    PENDING = "pending"
    WIN = "win"
    LOSS = "loss"
    EXPIRED = "expired"


class Settlement(BaseModel):
    """Validator Agent's settlement record. Written to Postgres + ValidatorSettle."""
    signal_id: Hex32
    publisher: EnsName
    outcome: Outcome
    pnl_bps_gross: int
    pnl_bps_net: int            # after gas + slippage attribution
    gas_bps: int
    execution_loss_bps: int     # carved out of net (attributed to buyer, not publisher)
    signal_loss_bps: int        # remaining (attributed to publisher)
    twap_at_horizon: float
    capital_deployed_usd: float
    distinct_buyers: int
    self_purchase_detected: bool
    settled_at_block: int
    settled_at_timestamp: int


# ─────────────────────────────────────────────────────────────────────────
# Reputation update (informational; the on-chain write is the source of truth)
# ─────────────────────────────────────────────────────────────────────────

class ReputationUpdate(BaseModel):
    """Computed reputation delta. The Validator posts this to ERC-8004."""
    agent_id: int
    signal_id: Hex32
    delta_score: int            # signed bps-weighted contribution
    weight: int                 # capital-weighted, sqrt-scaled
    new_score: Optional[int] = None  # filled after on-chain confirmation
    cold_start: bool = False    # half-weight if newcomer
    muted_reason: Optional[str] = None  # e.g. "no_distinct_buyers"
