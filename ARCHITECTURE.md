# SibylFi — Architecture

> The condensed reference. For the full strategic context see `signal_market_master_doc.md`.

## End-to-end signal lifecycle

```
┌────────────────────────────────────────────────────────────────────┐
│ Research Agent (one of 3 personas)                                 │
│ - Generates signal using local strategy + 0G Compute inference     │
│ - Signs payload with agent's private key                           │
│ - Persists metadata to 0G Storage                                  │
│ - Exposes /signal endpoint, x402-paywalled                         │
└──────────────────────────────┬─────────────────────────────────────┘
                               │
                               ▼
                  HTTP 402 → x402 payment → 200 with signed signal
                               │
                               ▼
┌────────────────────────────────────────────────────────────────────┐
│ Trading Agent                                                      │
│ - Discovers Research Agents via ERC-8004 IdentityRegistry          │
│ - Ranks by reputation (ReputationRegistry getter)                  │
│ - Pays via x402 (USDC, Base Sepolia)                               │
│ - Receives signed signal payload                                   │
└──────────────────────────────┬─────────────────────────────────────┘
                               │
                               ▼
┌────────────────────────────────────────────────────────────────────┐
│ Risk Agent (paid, x402)                                            │
│ - Verifies position size, slippage, vol bounds, liquidity floor    │
│ - Returns signed risk attestation                                  │
└──────────────────────────────┬─────────────────────────────────────┘
                               │
                               ▼ if risk OK
┌────────────────────────────────────────────────────────────────────┐
│ Uniswap Trading API (Base Sepolia)                                 │
│ - /v1/quote → /v1/swap with Permit2 signature                      │
│ - Trade settled on-chain                                           │
└──────────────────────────────┬─────────────────────────────────────┘
                               │
                               ▼ Trading Agent records execution receipt
                               ▼ (Postgres signal log)
                               ▼
                          [horizon elapses]
                               │
                               ▼
┌────────────────────────────────────────────────────────────────────┐
│ Validator Agent (cron, every minute)                               │
│ For each signal whose horizon expired:                             │
│   1. Read Uniswap V3 TWAP at horizon-end (5-min window)            │
│   2. Compute realized PnL gross                                    │
│   3. Deduct gas; apply slippage attribution                        │
│   4. Decide winner / loser / expired                               │
│   5. Post attestation to ERC-8004 ReputationRegistry (Sepolia)     │
│   6. Emit SignalSettled event from ValidatorSettle (Base Sepolia)  │
└────────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌────────────────────────────────────────────────────────────────────┐
│ Frontend Leaderboard (Next.js, Vercel)                             │
│ - Polls Orchestrator API every 5s                                  │
│ - Reorders Research Agents by capital-weighted 7d ROI              │
│ - Sonar pulse on the agent whose reputation just changed           │
└────────────────────────────────────────────────────────────────────┘
```

## Service topology (single VPS)

```
┌─ Hetzner CPX31 (Ubuntu 24.04, Docker Compose) ──────────────────────┐
│                                                                      │
│  Caddy reverse proxy (auto-TLS via Let's Encrypt) :80, :443         │
│      │                                                               │
│      ├── orchestrator     :7100   (FastAPI BFF for frontend)        │
│      ├── research-meanrev :7101   (FastAPI, x402 paywalled)         │
│      ├── research-momentum:7102                                      │
│      ├── research-news    :7103                                      │
│      ├── trading-agent    :7104                                      │
│      ├── risk-agent       :7105   (FastAPI, x402 paywalled)         │
│      └── validator-agent  :7106   (FastAPI + APScheduler)           │
│                                                                      │
│  Internal services (no external port):                              │
│      ├── sidecar-0gstorage :7000  (TS, wraps 0G Storage)            │
│      ├── postgres :5432           (signal log)                       │
│      └── redis :6379              (cache, x402 nonces)              │
└──────────────────────────────────────────────────────────────────────┘

External:
- Frontend on Vercel (talks to orchestrator over HTTPS)
- Sepolia, Base Sepolia, 0G Galileo testnets
- Coinbase x402 facilitator
- Uniswap Trading API
```

## Data persistence layers

| Layer | Tool | What it stores | Authoritative for |
|---|---|---|---|
| In-flight state | Postgres | Pending signals, executions, risk attestations | Active workflow |
| Reputation | ERC-8004 ReputationRegistry (Sepolia) | Per-agent attestations | Trust scores |
| Settlement events | ValidatorSettle (Base Sepolia) | Per-signal outcome + PnL | Settlement history |
| Agent identity | ENS subnames + ERC-8004 IdentityRegistry | Agent endpoint URLs + ENS names | Discovery |
| Agent memory | 0G Storage | Historical signal context (RAG) | Long-term agent learning |
| Cache | Redis | Leaderboard snapshots, x402 nonces | Performance only |

## Key contracts

**Deployed by us:**
- `ValidatorSettle.sol` (Base Sepolia, ~100 lines) — emits `SignalSettled(bytes32, bool, int256, uint256)`
- ENS Durin L2 Registrar (Base Sepolia) — mints subnames under `sibylfi.eth`

**Read but not deployed:**
- ERC-8004 IdentityRegistry v1.0 (Sepolia, `0x8004A169FB4a3325136EB29fA0ceB6D2e539a432`)
- ERC-8004 ReputationRegistry v1.0 (Sepolia, `0x8004BAa17C55a88189AE136b182e5fdA19dE9b63`)
- Uniswap Universal Router v2 (Base Sepolia, via Trading API)
- ENS Public Resolver (Sepolia, for ENSIP-25 text record reads)

> ⚠ Verify all contract addresses on the live block explorer before pinning the ABI. v0.4 → v1.0 was a breaking migration.

## Communication patterns

- **Frontend ↔ Orchestrator:** REST + 5s polling (could swap to WebSocket; polling is more demo-resilient)
- **Trading Agent → Research Agent:** HTTP GET `/signal` with `X-PAYMENT` header
- **Trading Agent → Risk Agent:** HTTP POST `/verify` with `X-PAYMENT` header
- **Trading Agent → Uniswap:** HTTPS to `trade-api.gateway.uniswap.org/v1/{quote,swap}`
- **Validator → ERC-8004:** Direct contract write via Viem (cross-chain via separate signed tx, no CCIP)
- **Research Agent → 0G Compute:** OpenAI-compatible HTTP via `@0glabs/0g-serving-broker`
- **All agents → 0G Storage:** Through TS sidecar (no first-party Python SDK)
