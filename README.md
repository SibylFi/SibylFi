# SibylFi

**A decentralized signal market where AI agents publish, buy, execute, and settle crypto trading signals on-chain.**

SibylFi connects a network of specialized AI agents through a verifiable economic loop: research agents publish signed signals behind an x402 paywall, a trading agent pays for access and executes the swap on Uniswap, a risk agent pre-screens every execution, and a validator agent settles outcomes using Uniswap V3 TWAP — posting the result to an ERC-8004 reputation registry so every agent's track record is public and immutable.

Built for **ETHGlobal Hackathon** · Deployed on **Base Sepolia** + **Sepolia**

---

## The Signal Market Loop

```
Research Agent  ──(signed signal)──►  0G Storage (IPFS-like pinning)
      │                                       │
      │  x402 paywall                         │ content hash
      ▼                                       ▼
Trading Agent  ──(pay + fetch)──►  Risk Agent (12 deterministic checks)
      │                                       │
      │  approved                             │
      ▼                                       ▼
Uniswap Trading API  ──(quote + swap)──►  ValidatorSettle.sol  (Base Sepolia)
                                               │
                                               │  TWAP + PnL
                                               ▼
                                     ERC-8004 ReputationRegistry  (Sepolia)
```

Every step is auditable: signals are EIP-712 signed, payments are x402-gated, swaps go through Uniswap Universal Router v2, outcomes are settled on-chain, and agent reputations are stored in a public ERC-8004 registry linked to ENS subnames.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Frontend (Next.js 15)  ◄──►  Orchestrator (FastAPI BFF :7100) │
└─────────────────────────────────────────────────────────────────┘
                                      │
          ┌───────────────────────────┼───────────────────────────┐
          ▼                           ▼                           ▼
  Research Agents              Trading Agent              Validator Agent
  swing  :7101                     :7104                      :7106
  scalper:7102                       │                           │
          │                     Risk Agent                  ValidatorSettle.sol
          │  0G Storage              :7105                  (Base Sepolia)
          ▼                                                       │
  sidecar-0gstorage :7000                                ERC-8004 Registry
  (@0gfoundation SDK)                                       (Sepolia)
          │
  ┌───────┴────────┐
  │   Postgres     │  Redis
  │   :5432        │  :6379
  └────────────────┘
```

**Networks used**

| Network | Purpose |
|---|---|
| Base Sepolia (chainId 84532) | Swaps (Uniswap), ValidatorSettle.sol, SibylFiRegistrar.sol |
| Sepolia (chainId 11155111) | ERC-8004 IdentityRegistry + ReputationRegistry |
| 0G Galileo testnet | 0G Storage + 0G Compute inference |

---

## Agents

| Agent | ENS name | Port | Role |
|---|---|---|---|
| **research-swing** | `swing.sibyl.eth` | 7101 | Swing signals (4H/1D) — 5-confluence strategy, EMA stack + Dow Theory |
| **research-scalper** | `scalper.sibyl.eth` | 7102 | Scalp signals (1m/5m) — adaptive ML setup score, multi-asset filter |
| **trading** | — | 7104 | Discovers agents via ERC-8004, buys signals, checks risk, executes swaps |
| **risk** | `risk.sibyl.eth` | 7105 | 12 deterministic pre-execution checks across 3 appetite profiles |
| **validator** | `validator.sibyl.eth` | 7106 | Settles expired signals via Uniswap V3 TWAP, posts PnL to ERC-8004 |
| **orchestrator** | — | 7100 | BFF for frontend (leaderboard, signal feed, demo endpoints) |

### Research Agent design

Research agents follow a **deterministic strategy engine + LLM calibrator** pattern. The rule-based engine (pure-Python Pine Script ports: EMA, RSI, ATR, Bollinger, SuperTrend, VWAP) decides direction and base confidence. The 0G Compute LLM reads the same snapshot and returns a `CONFIDENCE_DELTA` (±bps, clamped to ±1000) that adjusts the final score — the engine stays in control, the LLM adds judgment.

```
OHLCV snapshot
    │
    ├──► Strategy engine (indicators.py)  ──►  direction + base_confidence
    │
    └──► 0G Compute inference  ──►  CONFIDENCE_DELTA
                  │
                  ▼ (fallback)
          Anthropic API
```

### Risk Agent

Runs 12 checks before any swap is submitted:

- Position size vs. portfolio cap
- Slippage tolerance (bps)
- Uniswap V3 pool liquidity depth
- TWAP deviation from spot (anti-manipulation)
- Daily drawdown circuit breaker
- Signal age (staleness gate)
- Signature validity (EIP-712)
- Nonce replay guard
- Gas price ceiling
- Minimum confidence threshold
- Risk appetite enforcement (conservative / balanced / aggressive)
- Duplicate execution guard

---

## Smart Contracts

Both contracts are verified on Base Sepolia.

### ValidatorSettle.sol

Immutable on-chain settlement ledger. The validator agent calls `settle(signalId, outcome, pnlBps)` once per signal. Events are indexed for the reputation pipeline.

```
address: 0xDeA222163633301E0722f352D945DE557F1B024E  (Base Sepolia)
```

### SibylFiRegistrar.sol

ENS Durin L2 Registrar. Registers agent subnames under `sibyl.eth` and writes an ENSIP-25 text record (`agent-registration[chainId][registryAddr]`) that links each ENS name to the agent's ERC-8004 identity on Sepolia — bidirectional cross-chain identity.

```
address: 0xA2EFf18c8A5D34352c285aBfCFF6339034B83C64  (Base Sepolia)
L2Registry (Durin): 0x534207000512ff2d6859e300d7a138f114ef92b3  (Base Sepolia)
```

### Read-only contracts (not deployed by this project)

| Contract | Network | Address |
|---|---|---|
| ERC-8004 IdentityRegistry v1.0 | Sepolia | `0x8004A169FB4a3325136EB29fA0ceB6D2e539a432` |
| ERC-8004 ReputationRegistry v1.0 | Sepolia | `0x8004BAa17C55a88189AE136b182e5fdA19dE9b63` |

### Build & test contracts

```bash
cd contracts
forge build
forge test -vv
```

### Deploy

```bash
# ValidatorSettle
forge script script/DeployValidatorSettle.s.sol \
  --rpc-url $BASE_SEPOLIA_RPC --broadcast --verify

# SibylFiRegistrar
forge script script/DeploySibylFiRegistrar.s.sol \
  --rpc-url $BASE_SEPOLIA_RPC --broadcast --verify \
  --env-file ../.env
```

---

## Sponsor Integrations

### 0G — Storage + Compute

**0G Storage** is used to pin every published signal. The `sidecar-0gstorage` TypeScript service wraps `@0gfoundation/0g-storage-ts-sdk` and exposes a local HTTP API that Python agents call. Each signal gets a content hash stored on the 0G Galileo testnet that downstream agents use to retrieve and verify it.

**0G Compute** is the primary inference backend for research agents. The `agents/shared/inference.py` module calls 0G's OpenAI-compatible endpoint first, falling back to Anthropic if Galileo is unavailable.

```
agents/shared/inference.py          # 0G Compute via OpenAI-compat endpoint
sidecar-0gstorage/src/index.ts      # 0G Storage SDK wrapper
```

### Uniswap Foundation — Trading API + V3 TWAP

The **Trading Agent** calls the [Uniswap Trading API](https://docs.uniswap.org/api/trading-api/overview) to quote and execute swaps on Base Sepolia. The **Validator Agent** reads a Uniswap V3 TWAP to compute realized PnL — making Uniswap V3 pool prices the canonical settlement oracle for the entire reputation system.

```
agents/trading/uniswap.py           # /v1/quote + /v1/swap calls
agents/validator/twap.py            # IUniswapV3Pool TWAP for settlement
```

### ENS — Durin L2 + ENSIP-25

Every SibylFi agent has an ENS subname (`swing.sibyl.eth`, `risk.sibyl.eth`, etc.) minted by `SibylFiRegistrar.sol` on Base Sepolia via the Durin L2Registry. The registrar simultaneously writes an **ENSIP-25** text record linking each subname to the agent's ERC-8004 identity on Sepolia. The frontend verifies this link bidirectionally to display a trust badge.

```
contracts/src/SibylFiRegistrar.sol  # Durin L2 registrar + ENSIP-25 setText
frontend/lib/ensip25.ts             # Bidirectional verification
```

---

## Quick Start

### Prerequisites

- Docker + Docker Compose v2
- Node.js 20+ with pnpm (for local frontend dev)
- Python 3.12+ with pip (for local agent dev)
- Foundry (`foundryup`) for contract work

### 1. Clone and configure

```bash
git clone https://github.com/SibylFi/SibylFi.git
cd SibylFi
cp .env.example .env
```

Edit `.env`. For local development leave `MOCK_MODE=1` — the full signal loop runs offline with no testnet keys required.

### 2. Start all services

```bash
cd infra
docker compose up --build
```

| Service | URL |
|---|---|
| Frontend | http://localhost:3000 |
| Orchestrator | http://localhost:7100 |
| Research (swing) | http://localhost:7101 |
| Research (scalper) | http://localhost:7102 |
| Trading Agent | http://localhost:7104 |
| Risk Agent | http://localhost:7105 |
| Validator Agent | http://localhost:7106 |
| 0G Storage sidecar | http://localhost:7000 |

### 3. Run an end-to-end signal cycle (mock)

```bash
# Trigger the trading agent's discovery loop
curl -X POST http://localhost:7104/trade

# Check the signal feed
curl http://localhost:7100/signals

# Check agent leaderboard
curl http://localhost:7100/leaderboard
```

---

## MOCK_MODE

All external integrations (0G, Uniswap, ERC-8004, x402) have deterministic mock implementations. Set `MOCK_MODE=1` in `.env` to run the full pipeline offline.

| Integration | Mock behavior |
|---|---|
| 0G Compute | Deterministic stub keyed on `sha256(persona + prompt)` |
| 0G Storage | In-memory Map, no SDK calls |
| Uniswap Trading API | Synthetic quote with 0.3% mock spread |
| ERC-8004 registry | Reads from `agents/shared/mocks/erc8004_data.json` |
| x402 payments | Passthrough (no CDP calls) |
| TWAP | Reads from `agents/shared/mocks/twap_fixtures.json` |

See [`MOCK_MODE.md`](MOCK_MODE.md) for the full reference.

---

## Environment Variables

```bash
# ── Mode ──────────────────────────────────────────────────────────
MOCK_MODE=1                    # 1 = offline demo, 0 = live testnet
USE_FALLBACK_INFERENCE=0       # 1 = use Anthropic instead of 0G Compute

# ── Networks ──────────────────────────────────────────────────────
SEPOLIA_RPC=                   # Alchemy or Infura Sepolia endpoint
BASE_SEPOLIA_RPC=              # Base Sepolia endpoint
OG_GALILEO_RPC=https://evmrpc-testnet.0g.ai

# ── Agent wallets (one per agent) ─────────────────────────────────
RESEARCH_MEANREV_KEY=0x...
RESEARCH_MOMENTUM_KEY=0x...
RESEARCH_NEWS_KEY=0x...
TRADING_KEY=0x...
RISK_KEY=0x...
VALIDATOR_KEY=0x...

# ── Sponsor API keys ──────────────────────────────────────────────
COINBASE_CDP_KEY=              # x402 facilitator — portal.cdp.coinbase.com
UNISWAP_API_KEY=               # Trading API — hub.uniswap.org
ANTHROPIC_API_KEY=sk-ant-...   # Fallback inference only

# ── 0G Compute ────────────────────────────────────────────────────
OG_BROKER_KEY=0x...            # Wallet that pays 0G Compute invoices
OG_COMPUTE_ENDPOINT=           # Provider endpoint URL
OG_COMPUTE_API_KEY=            # Provider-issued key
OG_COMPUTE_MODEL=qwen3.6-plus

# ── Database / cache ──────────────────────────────────────────────
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_DB=sibylfi
POSTGRES_USER=sibylfi
POSTGRES_PASSWORD=

REDIS_HOST=redis
REDIS_PORT=6379

# ── Frontend ──────────────────────────────────────────────────────
NEXT_PUBLIC_ORCHESTRATOR_URL=http://localhost:7100
NEXT_PUBLIC_CHAIN_ID=84532
```

Full template: [`.env.example`](.env.example)

---

## Frontend

Built with **Next.js 15**, **React 18**, **Tailwind CSS**, **Wagmi**, and **Viem**.

Four views:

- **Leaderboard** — 7-day ROI ranking across all agents
- **Profile** — Individual agent stats, win/loss curve, reputation history
- **Rite** — Visual walkthrough of the signal lifecycle (publish → buy → risk → trade → settle)
- **Feed** — Real-time signal stream with execution status

### Local development

```bash
cd frontend
pnpm install
pnpm dev       # http://localhost:3000
```

The Next.js config proxies `/api/*` and `/demo/*` to the orchestrator at `:7100`.

---

## 0G Storage Sidecar

The `@0gfoundation/0g-storage-ts-sdk` is TypeScript-only. The sidecar is a small Express service that wraps it and exposes a language-agnostic HTTP API on port 7000 so Python agents can store and retrieve signal blobs without needing a TS runtime.

```
POST /upload              # Store a JSON blob; returns { hash }
GET  /download/:hash      # Retrieve a blob by SHA-256 hash
GET  /health              # Liveness probe
```

```bash
cd sidecar-0gstorage
pnpm install
pnpm dev
```

---

## Testing

### Agent unit tests

```bash
cd agents
python -m pytest shared/tests/ -v          # schema, base agent, indicators
python -m pytest shared/strategies/ -v    # swing + scalper strategies
```

### Contract tests

```bash
cd contracts
forge test -vv
```

### Health check (pre-demo)

```bash
bash scripts/check-health.sh
```

---

## Project Structure

```
SibylFi/
├── agents/
│   ├── shared/              # Shared modules (schema, DB, signing, inference, strategies)
│   │   ├── strategies/      # Pure-Python indicator library + swing/scalper engines
│   │   └── mocks/           # Deterministic fixtures for MOCK_MODE
│   ├── research_swing/      # Swing research agent (port 7101)
│   ├── research_scalper/    # Scalper research agent (port 7102)
│   ├── trading/             # Trading agent (port 7104)
│   ├── risk/                # Risk agent (port 7105)
│   ├── validator/           # Validator agent (port 7106)
│   └── orchestrator/        # Frontend BFF (port 7100)
├── contracts/
│   ├── src/                 # ValidatorSettle.sol, SibylFiRegistrar.sol
│   ├── script/              # Foundry deploy scripts
│   └── test/                # Foundry unit tests
├── frontend/                # Next.js 15 UI
├── sidecar-0gstorage/       # 0G Storage SDK bridge (TypeScript/Express)
├── infra/                   # docker-compose.yml + Caddyfile
├── specs/                   # Algorithm specs (validator, reputation math, risk thresholds)
├── scripts/                 # Operational helpers (health check, faucet drip)
├── demo/                    # Demo seeds + recording storyboard
├── ARCHITECTURE.md          # Service topology and data flow
├── MOCK_MODE.md             # Offline mock layer reference
├── REPO_LAYOUT.md           # Full file manifest
├── AI_USAGE.md              # AI assistance transparency log
└── FEEDBACK.md              # Sponsor DX feedback (prize requirement)
```

---

## Contributing

This is a hackathon project. The human team authors all strategy logic, contract design, and architectural decisions. AI tools assist with implementation. All AI-assisted work is logged in [`AI_USAGE.md`](AI_USAGE.md) per the hackathon transparency requirement.

### Git policy

- `main` is the only branch; no force-pushes.
- Commit messages use `scope: description` (e.g. `trading: add quote freshness check`).
- Never commit `.env`, private keys, or secrets.
- See [`AGENTS.md`](AGENTS.md) for the full policy.

---

## License

MIT
