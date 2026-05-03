# SibylFi Agents — v2 Status Dashboard

Last updated: 2026-05-03.

## Architecture (v2)

```
Research Agent (swing | scalper)             ← long-only, deterministic strategies
   │  publishes signed signal (x402-paid)
   ▼
Trading Agent
   │  reads signal → asks Risk → quotes Uniswap → swaps on Base Sepolia
   ▼
Risk Agent (profile-aware checks + appetite)  ← v2: 12 checks, 3 appetites
   │  attests pass/fail
   ▼
Trading Agent executes
   ▼
Validator Agent
   │  multi-checkpoint TWAP path-aware outcome resolver
   │  outcomes: WIN | WIN_PARTIAL | LOSS | EXPIRED | INCONCLUSIVE | INVALID
   ▼
ValidatorSettle.sol (Base Sepolia, immutable ledger)
   │
   ▼
ERC-8004 ReputationRegistry (Sepolia)
```

## Research Agents — 2 profiles

| Profile | ENS | Strategy | TF | Horizon | Confidence cap |
|---|---|---|---|---|---|
| **Swing** | `swing.sibylfi.eth` | Murphy + Dow + Elder, 5-confluence strict | 4H–1D | 1d–5d | 9000 bps |
| **Scalper** | `scalper.sibylfi.eth` | Adaptive ML (4 setups), anti-DD, multi-asset filter | 1m–5m | 30min–1h | 8500 bps |

Both **long-only** (schema-enforced). LLM is now a *calibrator* only — it nudges confidence within `[base, cap]` and writes the thesis. The strategy decides direction and base levels deterministically.

## Multi-tenant agent registry

Users register custom strategy bundles via `POST /api/agents` (frontend has the form). Each registration:
- Auto-generates a fresh demo wallet (eth_account)
- Stores `(profile, params, appetite, token, price)` in Postgres `custom_agents` table
- Exposes a per-agent `POST /api/agents/{id}/publish-signal` that runs the strategy in-process

Endpoint summary:

| Endpoint | Purpose |
|----------|---------|
| `GET /api/agents/_defaults/swing` | Default `SwingParams` for the form |
| `GET /api/agents/_defaults/scalper` | Default `ScalperParams` for the form |
| `POST /api/agents` | Register a new agent |
| `GET /api/agents` | List all custom agents |
| `GET /api/agents/{id}` | One record |
| `DELETE /api/agents/{id}` | Remove |
| `POST /api/agents/{id}/publish-signal` | Run the strategy; returns `published` + signal or `no_signal` + reason |
| `POST /demo/one-click-flow` | Seed `demo/seeds.json` agents + walk full lifecycle |

## v1 → v2 changes

### Schema (`agents/shared/signal_schema.py`)

| Field | v1 | v2 |
|-------|----|----|
| `direction` | `Literal["long","short"]` | **`Literal["long"]`** (short rejected) |
| `horizon_seconds` | 60–86400 | **300 – 1_209_600** (5min – 14d, covers Scalper 1m + Position roadmap) |
| `metadata` | absent | **`dict[str, Any] \| None`** (carries tp1, setup, tf, confluence, etc.) |

### Outcome enum (`Outcome`)

| Outcome | v1 | v2 |
|---------|----|----|
| `WIN`, `LOSS`, `EXPIRED`, `PENDING` | ✓ | ✓ |
| **`WIN_PARTIAL`** | — | TP1 hit + stop hit afterwards (multi-TP swing) |
| **`INCONCLUSIVE`** | — | oracle gap (not the agent's fault — reputation muted) |
| **`INVALID`** | — | reference-price mismatch / fraud-grade |

### Risk Agent

12 checks (`agents/risk/checks.py`): `POSITION_SIZE`, `RR_INSUFFICIENT`, `STOP_TOO_WIDE`, `SLIPPAGE`, `LIQUIDITY`, `EXHAUSTION`, `TWAP_DEVIATION`, `STOP_TOO_CLOSE`, `SELF_PURCHASE`, `ELDER_MONTH_RULE`, `MULTI_TP_INVALID`, `NON_LONG_REJECTED`. Profile-aware (swing/scalper/intraday floors) × appetite layer (conservative ~20% tighter / balanced identity / aggressive ~20% looser).

### Validator Agent

Multi-checkpoint TWAP outcome resolver (`agents/validator/algorithm.py`). `Checkpoint(price, t)` list replaces the v1 single-TWAP-at-horizon. Path-aware: detects which level was hit first.

```python
hit_target = first checkpoint with price ≥ target
hit_stop   = first checkpoint with price ≤ stop
hit_tp1    = first checkpoint with price ≥ tp1   (if metadata.tp1 present)

if hit_target before hit_stop      → WIN
if hit_tp1 before hit_stop         → WIN_PARTIAL  (PnL computed against tp1, not horizon)
if hit_stop                        → LOSS
if no checkpoints                  → INCONCLUSIVE
otherwise                          → EXPIRED
```

`reputation_update()` adds a half-credit branch for `WIN_PARTIAL` and a short-circuit for `INCONCLUSIVE`.

### Indicator math

Pure-Python ports in `agents/shared/strategies/indicators.py`. Wilder smoothing for RSI/ATR, Pine `ta.ema` semantics (alpha=2/(n+1)), population stdev for Bollinger. No third-party TA dependency — required for the deterministic mock-replay path.

Functions: `sma`, `ema`, `rsi`, `atr`, `bollinger`, `donchian`, `supertrend`, `vwap_session`, `volume_zscore`, `floor_pivots`, `detect_pivots_high/low`, `divergence_regular_bull/hidden_bull/regular_bear/hidden_bear`, `dow_bull_bars`.

### Strategy modules

`agents/shared/strategies/`:
- `snapshot.py` — `SwingFeatures`, `ScalperFeatures`, `StrategyResult`, `SwingParams`, `ScalperParams`
- `swing.py:24` — `evaluate_swing()` enforces 5-confluence + R3 cap + Brier-anchored confidence
- `scalper.py:30` — `evaluate_scalper()` enforces anti-DD + multi-asset filter + adaptive ML pick
- `feature_provider.py` — MOCK_MODE-aware snapshot loader (real OHLCV pipeline lands in v2.5)

## Test surface

Run inside the trading-agent (or any agent) container:

```bash
docker exec trading-agent python -m pytest \
  agents/shared/test_signal_schema.py \
  agents/risk/test_checks.py \
  agents/validator/test_algorithm.py \
  agents/shared/strategies/ \
  agents/shared/test_base_research_agent.py \
  orchestrator/test_custom_agents.py -q
```

103+ tests across schema, risk, validator, indicators, swing/scalper strategies, base agent, and the multi-tenant registry helpers.

## Demo flow

Hit `POST /demo/one-click-flow` (or click the demo button in the frontend). The orchestrator:

1. Loads `demo/seeds.json` (3 pre-baked agents)
2. Registers each into the multi-tenant registry (idempotent — reuses existing rows)
3. Publishes a signal from each
4. Runs one trading-agent `/trade` pass
5. Runs one validator `/settle-now` pass
6. Returns a structured trace with timings

Expected per the seeds:
- `trend-hunter.sibylfi.eth` (swing) — **published**, setup `strict_5_confluence`, horizon 1d
- `pulse-scalper.sibylfi.eth` (scalper) — **published**, setup `Pullback`, horizon 1h
- `patient-sage.sibylfi.eth` (swing, conservative) — **no_signal** with reason `dow_streak_too_short:22<30` (showcases the rejection path)

## Security posture

After the May 2026 incident:
- All agent ports (`7100`–`7106`) bound to `127.0.0.1` only — internet-facing surface is `:80/:443` (Caddy) plus SSH
- Frontend container does NOT load `.env` — it only sees `NEXT_PUBLIC_ORCHESTRATOR_URL`
- Frontend image runs Next.js `^15.2.4` (locked above CVE-2025-29927 patch boundary)
- Caddy routes `/signal/swing/*` and `/signal/scalper/*` only (legacy routes removed)

## Status

| Track | Status |
|-------|--------|
| Schema, risk, validator, base agent, indicators, strategies | ✅ green |
| Multi-tenant registry + frontend AgentForm | ✅ green |
| Demo seed configs + one-click flow | ✅ green |
| Real OHLCV→features pipeline (replaces `mock_features.json`) | 🟡 v2.5 |
| Real x402 payment flow on signal access | 🟡 v2.5 |
| Real Uniswap V3 TWAP read in `read_checkpoints` | 🟡 v2.5 |
