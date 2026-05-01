"""
Orchestrator API — frontend's BFF.

Aggregates state from ERC-8004, ValidatorSettle events, and Postgres into
the shapes the frontend needs. Polled every 5 seconds by the leaderboard.

Also exposes /demo/* endpoints that judges' demo-mode controls hit.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

import httpx
import structlog
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from agents.shared.db import close_pool, db_conn, init_pool
from agents.shared.erc8004_client import ERC8004Client
from agents.shared.logging_setup import setup_logging
from agents.shared.settings import get_settings

log = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging("orchestrator")
    await init_pool()
    yield
    await close_pool()


app = FastAPI(title="SibylFi Orchestrator", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in prod
    allow_methods=["*"],
    allow_headers=["*"],
)

_settings = get_settings()
_erc8004 = ERC8004Client()


# ─────────────────────────────────────────────────────────────────────────
# Models
# ─────────────────────────────────────────────────────────────────────────

class LeaderboardEntry(BaseModel):
    agent_id: int
    ens_name: str
    address: str
    endpoint: str
    reputation_score: int
    total_attestations: int
    wins: int
    losses: int
    win_rate: float
    roi_7d_bps: int
    capital_served_usd: float
    cold_start: bool


class SignalRow(BaseModel):
    signal_id: str
    publisher: str
    token: str
    direction: str
    reference_price: float
    target_price: float
    stop_price: float
    horizon_seconds: int
    confidence_bps: int
    published_at: datetime
    horizon_expires_at: datetime
    settled: bool
    outcome: Optional[str] = None
    pnl_bps_net: Optional[int] = None
    capital_deployed_usd: Optional[float] = None


# ─────────────────────────────────────────────────────────────────────────
# Read endpoints
# ─────────────────────────────────────────────────────────────────────────

@app.get("/api/leaderboard")
async def leaderboard() -> list[LeaderboardEntry]:
    """Aggregated leaderboard — ranks agents by 7d ROI."""
    agents = _erc8004.list_agents()
    entries = []
    for a in agents:
        stats = _erc8004.get_stats(a.agent_id)
        win_rate = stats.wins / max(1, stats.total_attestations)

        async with db_conn() as conn:
            async with conn.cursor() as cur:
                # Capital-weighted 7d ROI: sum(capital * pnl) / sum(capital)
                await cur.execute(
                    """
                    SELECT
                      COALESCE(SUM(s.capital_deployed_usd * s.pnl_bps_net) / NULLIF(SUM(s.capital_deployed_usd), 0), 0) AS roi_7d,
                      COALESCE(SUM(s.capital_deployed_usd), 0) AS capital_total
                    FROM settlements s
                    WHERE s.publisher = %s AND s.settled_at > NOW() - INTERVAL '7 days'
                    """,
                    (a.ens_name,),
                )
                row = await cur.fetchone()
                roi_7d_bps = int(row[0] or 0)
                capital_total = float(row[1] or 0)

        entries.append(LeaderboardEntry(
            agent_id=a.agent_id,
            ens_name=a.ens_name,
            address=a.owner,
            endpoint=a.endpoint,
            reputation_score=stats.score,
            total_attestations=stats.total_attestations,
            wins=stats.wins,
            losses=stats.losses,
            win_rate=round(win_rate, 4),
            roi_7d_bps=roi_7d_bps,
            capital_served_usd=capital_total,
            cold_start=stats.total_attestations < 5,
        ))

    entries.sort(key=lambda e: e.roi_7d_bps, reverse=True)
    return entries


@app.get("/api/signals")
async def signals(limit: int = 50, status: Optional[str] = None) -> list[SignalRow]:
    """Recent signals, optionally filtered by settlement status."""
    where = []
    params: list = []
    if status == "live":
        where.append("s.settled = FALSE AND s.horizon_expires_at > NOW()")
    elif status == "settled":
        where.append("s.settled = TRUE")
    elif status == "expired":
        where.append("s.settled = FALSE AND s.horizon_expires_at <= NOW()")
    where_sql = "WHERE " + " AND ".join(where) if where else ""

    sql = f"""
        SELECT
          s.signal_id, s.publisher, s.token, s.direction,
          s.reference_price, s.target_price, s.stop_price,
          s.horizon_seconds, s.confidence_bps,
          s.published_at, s.horizon_expires_at, s.settled,
          ss.outcome, ss.pnl_bps_net, ss.capital_deployed_usd
        FROM signals s
        LEFT JOIN settlements ss ON ss.signal_id = s.signal_id
        {where_sql}
        ORDER BY s.published_at DESC
        LIMIT %s
    """
    params.append(limit)

    async with db_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(sql, params)
            rows = await cur.fetchall()

    return [
        SignalRow(
            signal_id=r[0],
            publisher=r[1],
            token=r[2],
            direction=r[3],
            reference_price=float(r[4]),
            target_price=float(r[5]),
            stop_price=float(r[6]),
            horizon_seconds=int(r[7]),
            confidence_bps=int(r[8]),
            published_at=r[9],
            horizon_expires_at=r[10],
            settled=bool(r[11]),
            outcome=r[12],
            pnl_bps_net=int(r[13]) if r[13] is not None else None,
            capital_deployed_usd=float(r[14]) if r[14] is not None else None,
        )
        for r in rows
    ]


@app.get("/api/agent/{ens_name}")
async def agent_detail(ens_name: str) -> dict:
    """Full detail for a single agent — for the profile view."""
    agents = _erc8004.list_agents()
    target = next((a for a in agents if a.ens_name == ens_name), None)
    if not target:
        raise HTTPException(status_code=404, detail=f"agent {ens_name} not found")

    stats = _erc8004.get_stats(target.agent_id)

    return {
        "agent_id": target.agent_id,
        "ens_name": target.ens_name,
        "address": target.owner,
        "endpoint": target.endpoint,
        "registered_at": target.registered_at,
        "reputation": stats.__dict__,
        "ensip25_text_record_key": (
            f"agent-registration[{_settings.CHAIN_ID_SEPOLIA}]"
            f"[0x8004A169FB4a3325136EB29fA0ceB6D2e539a432]"
        ),
        "ensip25_text_record_value": str(target.agent_id),
    }


# ─────────────────────────────────────────────────────────────────────────
# Demo control endpoints — for the recording rig
# ─────────────────────────────────────────────────────────────────────────

@app.post("/demo/publish-signal")
async def demo_publish_signal(persona: str = "meanrev", token: str = "WETH/USDC") -> dict:
    """Trigger a Research Agent to publish a signal. Used by the demo control panel."""
    port_map = {"meanrev": 7101, "momentum": 7102, "news": 7103}
    port = port_map.get(persona, 7101)
    url = f"http://research-{persona}:{port}/signal?token={token}"

    # Note: in real mode this requires x402 payment; demo mode bypasses by using mock_mode
    async with httpx.AsyncClient(timeout=15.0) as client:
        # Send fake payment header — middleware accepts any in MOCK_MODE
        r = await client.get(url, headers={"X-PAYMENT": "demo-mock-token"})
        if r.status_code != 200:
            raise HTTPException(status_code=502, detail=f"agent returned {r.status_code}: {r.text}")
        return r.json()


@app.post("/demo/settle-now")
async def demo_settle_now() -> dict:
    """Force the validator to settle any expired signals. Used during demo recording."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post("http://validator-agent:7106/settle-now")
        return r.json()


@app.post("/demo/trade-now")
async def demo_trade_now(token: str = "WETH/USDC", capital_usd: float = 1000.0) -> dict:
    """Trigger the trading agent to discover and trade. Used during demo recording."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(
            f"http://trading-agent:7104/trade?token={token}&capital_usd={capital_usd}"
        )
        return r.json()


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "ts": datetime.now(timezone.utc).isoformat()}
