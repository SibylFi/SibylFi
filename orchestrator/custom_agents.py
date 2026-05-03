"""
Multi-tenant Research Agent registry.

Users register a custom agent through the frontend; each row in
`custom_agents` describes a strategy bundle (profile + params + identity)
that the orchestrator can run on demand.

Endpoints under /api/agents are mounted by orchestrator/main.py. The
strategy module is selected by `profile`; params_json is deserialized
into the matching dataclass and passed to BaseResearchAgent.

Wallets: agents need an Ethereum identity to sign their signals. For the
demo we auto-generate a fresh eth_account on registration and persist
the private key in Postgres. **This is demo-grade only** — production
would integrate a custodial signer or KMS.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any, Literal

import structlog
from eth_account import Account
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from agents.shared.base_research_agent import BaseResearchAgent, PersonaConfig
from agents.shared.db import db_conn
from agents.shared.strategies.snapshot import ScalperParams, SwingParams

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/agents", tags=["custom-agents"])

Profile = Literal["swing", "scalper"]
Appetite = Literal["conservative", "balanced", "aggressive"]


# ─── Wire models ─────────────────────────────────────────────────────────


class CreateAgentRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=80)
    ens_name: str = Field(pattern=r"^[a-z0-9-]+\.sibylfi\.eth$")
    profile: Profile
    token: str = "WETH/USDC"
    appetite: Appetite = "balanced"
    price_per_signal_usdc: float = Field(default=0.50, gt=0)
    params: dict[str, Any] = Field(default_factory=dict)


class AgentRecord(BaseModel):
    id: int
    ens_name: str
    display_name: str
    profile: Profile
    appetite: Appetite
    token: str
    price_per_signal_usdc: float
    address: str
    params: dict[str, Any]
    created_at: str


class PublishResponse(BaseModel):
    status: Literal["published", "no_signal"]
    reason: str | None = None
    signal: dict[str, Any] | None = None


# ─── Param hydration ─────────────────────────────────────────────────────


def _hydrate_params(profile: Profile, raw: dict[str, Any]) -> SwingParams | ScalperParams:
    """Build a typed params dataclass, ignoring keys the dataclass doesn't accept."""
    cls = SwingParams if profile == "swing" else ScalperParams
    valid = {f for f in cls.__dataclass_fields__}
    cleaned = {k: v for k, v in raw.items() if k in valid}
    return cls(**cleaned)


def _persona_from_row(row: dict) -> PersonaConfig:
    profile = row["profile"]
    params = _hydrate_params(profile, row["params_json"] or {})
    return PersonaConfig(
        name=row["ens_name"].split(".")[0],
        profile=profile,
        ens_name=row["ens_name"],
        private_key=row["private_key"],
        price_per_signal_usdc=float(row["price_per_signal_usdc"]),
        prompt_template=_default_prompt(profile),
        swing_params=params if profile == "swing" else None,
        scalper_params=params if profile == "scalper" else None,
    )


def _default_prompt(profile: Profile) -> str:
    return (
        f"You are calibrating a deterministic {profile.upper()} signal — "
        "direction and base levels are fixed by the rule engine. Suggest "
        "a small confidence delta in basis points and one short thesis.\n\n"
        "Token: {token}\nProfile: {profile}\nSetup: {setup}\n"
        "Reference price (TWAP30): {reference_price}\nTarget: {target_price}\n"
        "Stop: {stop_price}\nHorizon (s): {horizon_seconds}\n"
        "Base confidence (bps): {confidence_base}\nCap (bps): {confidence_cap}\n\n"
        "Output EXACTLY two lines:\n"
        "CONFIDENCE_DELTA: <signed integer in [-300, +300]>\n"
        "THESIS: <one sentence, no newlines>\n"
    )


def _row_to_record(row: dict) -> AgentRecord:
    pk = row["private_key"]
    addr = Account.from_key(pk).address
    return AgentRecord(
        id=row["id"],
        ens_name=row["ens_name"],
        display_name=row["display_name"],
        profile=row["profile"],
        appetite=row["appetite"],
        token=row["token"],
        price_per_signal_usdc=float(row["price_per_signal_usdc"]),
        address=addr,
        params=row["params_json"] or {},
        created_at=row["created_at"].isoformat() if row["created_at"] else "",
    )


async def _fetch_row(agent_id: int) -> dict | None:
    async with db_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT id, ens_name, display_name, profile, appetite, token, "
                "price_per_signal_usdc, params_json, owner_address, private_key, created_at "
                "FROM custom_agents WHERE id = %s",
                (agent_id,),
            )
            r = await cur.fetchone()
    if not r:
        return None
    return {
        "id": r[0], "ens_name": r[1], "display_name": r[2], "profile": r[3],
        "appetite": r[4], "token": r[5], "price_per_signal_usdc": r[6],
        "params_json": r[7], "owner_address": r[8], "private_key": r[9],
        "created_at": r[10],
    }


# ─── Endpoints ───────────────────────────────────────────────────────────


@router.post("", response_model=AgentRecord)
async def create_agent(req: CreateAgentRequest) -> AgentRecord:
    # Validate params hydrate cleanly before insert
    try:
        _hydrate_params(req.profile, req.params)
    except TypeError as e:
        raise HTTPException(400, f"invalid params for profile={req.profile}: {e}")

    acct = Account.create()
    async with db_conn() as conn:
        async with conn.cursor() as cur:
            try:
                await cur.execute(
                    """
                    INSERT INTO custom_agents (
                        ens_name, display_name, profile, appetite, token,
                        price_per_signal_usdc, params_json, owner_address, private_key
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
                    RETURNING id, ens_name, display_name, profile, appetite, token,
                              price_per_signal_usdc, params_json, owner_address,
                              private_key, created_at
                    """,
                    (
                        req.ens_name, req.display_name, req.profile, req.appetite,
                        req.token, req.price_per_signal_usdc,
                        json.dumps(req.params), acct.address, acct.key.hex(),
                    ),
                )
                r = await cur.fetchone()
            except Exception as e:
                # Most likely a UNIQUE violation on ens_name
                if "duplicate key" in str(e).lower() or "unique" in str(e).lower():
                    raise HTTPException(409, f"ens_name already registered: {req.ens_name}")
                raise
        await conn.commit()

    row = {
        "id": r[0], "ens_name": r[1], "display_name": r[2], "profile": r[3],
        "appetite": r[4], "token": r[5], "price_per_signal_usdc": r[6],
        "params_json": r[7], "owner_address": r[8], "private_key": r[9],
        "created_at": r[10],
    }
    log.info("custom_agent_registered", id=row["id"], ens=row["ens_name"], profile=row["profile"])
    return _row_to_record(row)


@router.get("", response_model=list[AgentRecord])
async def list_agents() -> list[AgentRecord]:
    async with db_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT id, ens_name, display_name, profile, appetite, token, "
                "price_per_signal_usdc, params_json, owner_address, private_key, created_at "
                "FROM custom_agents ORDER BY created_at DESC"
            )
            rows = await cur.fetchall()
    return [
        _row_to_record({
            "id": r[0], "ens_name": r[1], "display_name": r[2], "profile": r[3],
            "appetite": r[4], "token": r[5], "price_per_signal_usdc": r[6],
            "params_json": r[7], "owner_address": r[8], "private_key": r[9],
            "created_at": r[10],
        })
        for r in rows
    ]


@router.get("/{agent_id}", response_model=AgentRecord)
async def get_agent(agent_id: int) -> AgentRecord:
    row = await _fetch_row(agent_id)
    if row is None:
        raise HTTPException(404, f"agent {agent_id} not found")
    return _row_to_record(row)


@router.delete("/{agent_id}")
async def delete_agent(agent_id: int) -> dict:
    async with db_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute("DELETE FROM custom_agents WHERE id = %s", (agent_id,))
            deleted = cur.rowcount
        await conn.commit()
    if deleted == 0:
        raise HTTPException(404, f"agent {agent_id} not found")
    log.info("custom_agent_deleted", id=agent_id)
    return {"deleted": agent_id}


@router.post("/{agent_id}/publish-signal", response_model=PublishResponse)
async def publish_signal(
    agent_id: int,
    token: str | None = None,
    published_at_block: int = 12_345_678,
) -> PublishResponse:
    """Run the custom agent's strategy and emit a signal (or describe rejection)."""
    row = await _fetch_row(agent_id)
    if row is None:
        raise HTTPException(404, f"agent {agent_id} not found")

    persona = _persona_from_row(row)
    use_token = token or row["token"]
    agent = BaseResearchAgent(persona)

    sig = await agent.generate_signal(token=use_token, published_at_block=published_at_block)
    if sig is None:
        reason = "unknown"
        if agent.last_strategy_result is not None:
            reason = agent.last_strategy_result.reason
        log.info("custom_agent_no_signal", id=agent_id, reason=reason)
        return PublishResponse(status="no_signal", reason=reason)

    return PublishResponse(status="published", signal=sig.model_dump())


# ─── Helper: dump effective params ───────────────────────────────────────


def serialize_default_params(profile: Profile) -> dict[str, Any]:
    """Return the default param dict for a profile — used by the frontend
    to pre-fill the agent-creation form."""
    cls = SwingParams if profile == "swing" else ScalperParams
    return asdict(cls())


@router.get("/_defaults/{profile}", response_model=dict)
async def get_default_params(profile: Profile) -> dict:
    return {"profile": profile, "params": serialize_default_params(profile)}
