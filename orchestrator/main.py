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
from agents.shared.strategies.feature_provider import load_features
from agents.shared.strategies.scalper import evaluate_scalper
from agents.shared.strategies.snapshot import ScalperParams, SwingParams
from agents.shared.strategies.swing import evaluate_swing
from orchestrator.custom_agents import router as custom_agents_router

log = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging("orchestrator")
    await init_pool()
    yield
    await close_pool()


app = FastAPI(title="SibylFi Orchestrator", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in prod
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(custom_agents_router)

_settings = get_settings()
_erc8004 = ERC8004Client()

# Cache the agent → price lookup. The leaderboard polls every 5 seconds; without
# caching we'd issue an HTTP per agent per poll. Prices change rarely (only on
# custom-agent creation or persona-config edit), so a 60s TTL is safe.
_PRICE_CACHE: dict[str, tuple[float, float]] = {}   # ens_name → (price, fetched_at_unix)
_PRICE_TTL_SECONDS = 60.0


async def _resolve_price_per_signal(ens_name: str, endpoint: str) -> Optional[float]:
    """Return the agent's USDC price per signal, or None if it can't be resolved.

    Three sources, in order:
      1. custom_agents row (user-registered agents store price at create time)
      2. the agent service's `/` endpoint (default personas read this from
         PersonaConfig)
      3. None (caller decides what fallback, if any, to display)
    """
    import time
    now = time.time()
    cached = _PRICE_CACHE.get(ens_name)
    if cached and now - cached[1] < _PRICE_TTL_SECONDS:
        return cached[0]

    price: Optional[float] = None

    # 1. custom_agents table
    try:
        async with db_conn() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT price_per_signal_usdc FROM custom_agents WHERE ens_name = %s",
                    (ens_name,),
                )
                row = await cur.fetchone()
                if row and row[0] is not None:
                    price = float(row[0])
    except Exception as e:
        log.warning("price_lookup_db_failed", ens=ens_name, error=str(e))

    # 2. fall through to the agent's HTTP root
    if price is None and endpoint:
        # `endpoint` looks like http://research-swing:7101/signal — we want the
        # service root.
        root = endpoint.rsplit("/", 1)[0] + "/"
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                r = await client.get(root)
                if r.status_code == 200:
                    body = r.json()
                    p = body.get("price_per_signal_usdc")
                    if p is not None:
                        price = float(p)
        except (httpx.HTTPError, ValueError) as e:
            log.warning("price_lookup_http_failed", ens=ens_name, root=root, error=str(e))

    if price is not None:
        _PRICE_CACHE[ens_name] = (price, now)
    return price


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
    price_per_signal_usdc: Optional[float] = None


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

        price_usdc = await _resolve_price_per_signal(a.ens_name, a.endpoint)

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
            price_per_signal_usdc=price_usdc,
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
# Strategy preview — read-only "what would publish right now"
# ─────────────────────────────────────────────────────────────────────────
#
# Runs every (core publisher × supported token) strategy in-process so the UI
# can show buyers which combos are firing before they commit USDC. No HTTP
# between agents, no x402, no LLM call — just feature_provider + evaluate_*.

_PREVIEW_PUBLISHERS: list[tuple[str, str]] = [
    # (publisher_ens, profile)
    ("swing.sibylfi.eth",   "swing"),
    ("scalper.sibylfi.eth", "scalper"),
]
_PREVIEW_TOKENS: list[str] = ["WETH/USDC", "WBTC/USDC", "ARB/USDC", "OP/USDC"]


class StrategyPreviewRow(BaseModel):
    publisher_ens: str
    profile: str
    token: str
    accept: bool
    setup: Optional[str] = None
    reason: Optional[str] = None


class StrategyPreview(BaseModel):
    fetched_at: datetime
    rows: list[StrategyPreviewRow]


@app.get("/api/strategy-preview")
async def strategy_preview() -> StrategyPreview:
    """Probe every (core publisher × token) combo. Read-only.

    Computes the same gates the paid /signal endpoint runs but without
    purchasing or signing anything. Useful as a "what's firing" dashboard
    before committing capital through /demo/trade-now.
    """
    swing_params = SwingParams()
    scalper_params = ScalperParams()
    rows: list[StrategyPreviewRow] = []
    for ens, profile in _PREVIEW_PUBLISHERS:
        params = swing_params if profile == "swing" else scalper_params
        evalfn = evaluate_swing if profile == "swing" else evaluate_scalper
        for token in _PREVIEW_TOKENS:
            try:
                feat = load_features(profile, token)
                res = evalfn(feat, params)
                rows.append(StrategyPreviewRow(
                    publisher_ens=ens, profile=profile, token=token,
                    accept=res.accept,
                    setup=res.setup if res.accept else None,
                    reason=None if res.accept else res.reason,
                ))
            except Exception as e:
                log.warning("strategy_preview_probe_failed", ens=ens, token=token, error=str(e))
                rows.append(StrategyPreviewRow(
                    publisher_ens=ens, profile=profile, token=token,
                    accept=False, reason=f"probe_error:{type(e).__name__}",
                ))
    return StrategyPreview(fetched_at=datetime.now(timezone.utc), rows=rows)


# ─────────────────────────────────────────────────────────────────────────
# Demo control endpoints — for the recording rig
# ─────────────────────────────────────────────────────────────────────────

@app.post("/demo/publish-signal")
async def demo_publish_signal(persona: str = "swing", token: str = "WETH/USDC") -> dict:
    """Trigger a Research Agent to publish a signal. Used by the demo control panel.

    Goes through the real x402 paywall using TRADING_KEY as the payer — clicking
    this button moves real USDC on Base Sepolia (or whichever network MOCK_MODE
    points at). Strategy may decline this bar; that surfaces as 204.
    """
    from eth_account import Account
    from agents.shared.x402_client import fetch_paywalled

    port_map = {"swing": 7101, "scalper": 7102}
    if persona not in port_map:
        raise HTTPException(status_code=400, detail=f"unknown persona: {persona}; expected swing|scalper")
    url = f"http://research-{persona}:{port_map[persona]}/signal?token={token}"

    payer_priv_key = _settings.TRADING_KEY
    payer_addr = Account.from_key(payer_priv_key).address

    try:
        result = await fetch_paywalled(
            url=url,
            payer_addr=payer_addr,
            payer_priv_key=payer_priv_key,
            method="GET",
        )
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))

    if result.body is None:
        return {"status": "no_signal", "reason": "strategy_declined", "persona": persona}
    return result.body


@app.post("/demo/settle-now")
async def demo_settle_now() -> dict:
    """Force the validator to settle any expired signals. Used during demo recording."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post("http://validator-agent:7106/settle-now")
        return r.json()


@app.post("/demo/trade-now")
async def demo_trade_now(
    token: str = "WETH/USDC",
    capital_usd: float = 1000.0,
    publisher_ens: Optional[str] = None,
) -> dict:
    """Trigger the trading agent to discover and trade. Used during demo recording.

    publisher_ens (optional): pin the buy to a specific Research Agent ENS,
    e.g. "swing.sibylfi.eth". Without it, trade-now picks the highest-
    reputation agent.
    """
    params = {"token": token, "capital_usd": capital_usd}
    if publisher_ens:
        params["publisher_ens"] = publisher_ens
    async with httpx.AsyncClient(timeout=180.0) as client:
        r = await client.post("http://trading-agent:7104/trade", params=params)
        return r.json()


# ─── One-click v2 demo flow ──────────────────────────────────────────────


@app.post("/demo/one-click-flow")
async def demo_one_click_flow() -> dict:
    """
    Seed `demo/seeds.json` agents into the registry, then walk each one
    through publish → expected outcome. Returns a step-by-step trace that
    the demo storyboard narrates over.

    Idempotent: if an ENS name is already registered, the existing record
    is reused. The endpoint is safe to call repeatedly during recording.
    """
    import json as _json
    import time as _time
    from pathlib import Path

    from orchestrator.custom_agents import (
        CreateAgentRequest,
        create_agent,
        list_agents,
        publish_signal,
    )

    seeds_path = Path("/app/demo/seeds.json")
    if not seeds_path.exists():
        raise HTTPException(500, "demo/seeds.json missing in image")
    seeds = _json.loads(seeds_path.read_text())

    started = _time.time()
    trace: list[dict] = []

    existing = {a.ens_name: a for a in await list_agents()}

    for entry in seeds["agents"]:
        ens = entry["ens_name"]
        if ens in existing:
            agent_record = existing[ens]
            trace.append({"step": "register", "ens": ens, "status": "already_registered", "id": agent_record.id})
        else:
            req = CreateAgentRequest(
                display_name=entry["display_name"],
                ens_name=ens,
                profile=entry["profile"],
                token=entry.get("token", "WETH/USDC"),
                appetite=entry.get("appetite", "balanced"),
                price_per_signal_usdc=entry.get("price_per_signal_usdc", 0.50),
                params=entry.get("params", {}),
            )
            agent_record = await create_agent(req)
            trace.append({
                "step": "register", "ens": ens, "status": "created",
                "id": agent_record.id, "address": agent_record.address,
            })

        # Publish a signal
        pub = await publish_signal(agent_record.id, token=entry.get("token", "WETH/USDC"))
        if pub.status == "published" and pub.signal:
            sig = pub.signal
            trace.append({
                "step": "publish", "ens": ens, "status": "published",
                "signal_id": sig.get("signal_id"),
                "setup": sig.get("metadata", {}).get("setup") or sig.get("metadata", {}).get("rr_structure"),
                "confidence_bps": sig.get("confidence_bps"),
                "target": sig.get("target_price"),
                "stop": sig.get("stop_price"),
                "horizon_seconds": sig.get("horizon_seconds"),
            })
        else:
            trace.append({
                "step": "publish", "ens": ens, "status": "no_signal",
                "reason": pub.reason,
            })

    # Trigger one trade-pass + one settlement-pass for the lifecycle visual
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            r = await client.post("http://trading-agent:7104/trade?token=WETH%2FUSDC&capital_usd=1000")
            trace.append({"step": "trade", "status": r.status_code, "body": r.json() if r.status_code == 200 else r.text[:300]})
        except Exception as e:
            trace.append({"step": "trade", "status": "error", "error": str(e)})

        try:
            r = await client.post("http://validator-agent:7106/settle-now")
            trace.append({"step": "settle", "status": r.status_code, "body": r.json() if r.status_code == 200 else r.text[:300]})
        except Exception as e:
            trace.append({"step": "settle", "status": "error", "error": str(e)})

    return {
        "elapsed_seconds": round(_time.time() - started, 2),
        "agents_seeded": len(seeds["agents"]),
        "trace": trace,
    }


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "ts": datetime.now(timezone.utc).isoformat()}
