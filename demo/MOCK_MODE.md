# MOCK_MODE — running SibylFi offline

When `MOCK_MODE=1` in `.env`, the system runs end-to-end without any real
testnet transactions. This is the default for local development.

## What's mocked

| Component | Real behavior | Mock behavior |
|---|---|---|
| ERC-8004 reads | Calls `IdentityRegistry.getAgent()` on Sepolia | Returns from `agents/shared/mocks/erc8004_data.json` |
| ERC-8004 writes | Validator posts attestation transaction | Logs the attestation to stdout |
| 0G Compute | OpenAI-compatible call to provider | Returns a deterministic stub response |
| 0G Storage | Writes to TS sidecar → 0G network | Stores in local Postgres `mock_storage` table |
| x402 facilitator | Calls Coinbase CDP `/verify` | Always returns `verified: true` after token check |
| Uniswap Trading API | HTTPS to `trade-api.gateway.uniswap.org` | Returns synthetic quote based on current TWAP fixture |
| Uniswap V3 TWAP read | Calls `pool.observe()` on Base Sepolia | Reads from `agents/shared/mocks/twap_fixtures.json` |
| ENS resolution | Wagmi `useEnsName` → CCIP-Read | Resolves from `frontend/lib/mocks/ens_records.json` |

## What's NOT mocked

- Internal HTTP between agents (still real FastAPI, real x402 headers)
- Database (real Postgres)
- Redis (real Redis)
- The signal schema validation (real Pydantic)
- The validator algorithm itself (real math, real reputation updates)
- The frontend (real Next.js, real animations)

This means you can develop and test the entire SibylFi pipeline — agent
discovery, payment flow, signal validation, reputation update, leaderboard
reordering — without any external dependencies. The same code paths execute;
only the leaf-level external calls are stubbed.

## Switching to real testnets

```bash
# In .env, flip the flag:
MOCK_MODE=0

# Provide real keys for everything in .env:
SEPOLIA_RPC=...
BASE_SEPOLIA_RPC=...
OG_GALILEO_RPC=...
COINBASE_CDP_KEY=...
UNISWAP_API_KEY=...
# ...all wallet keys funded from respective faucets

# Restart
docker compose -f infra/docker-compose.yml restart
```

The codebase has explicit `if settings.MOCK_MODE:` branches at every external
boundary. Search for `MOCK_MODE` in the codebase to see every affected call
site.

## Why this matters

A reference implementation that requires live testnet credentials to even
start is hostile to anyone studying it. The mock layer makes the architecture
inspectable in isolation, which is the whole point of a reference repo.

For the actual hackathon submission, you'll want `MOCK_MODE=0` for the demo
recording (judges expect to see real ERC-8004 attestations on a block
explorer). But during build days, leave it on.
