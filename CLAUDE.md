# Claude Instructions — SibylFi App Repo

This is the SibylFi application repository. Skills live in `.claude/skills/`.

## Before working

1. Read `AGENTS.md` — git policy, commit shape, AI attribution rules.
2. Read `docs/SIGNAL_MARKET_CONTEXT.md` in the Skills-Hackathon pack, or the summary below.
3. Load the relevant `.claude/skills/<skill-name>/SKILL.md` for the current task.

## Signal Market context (summary)

SibylFi is a decentralized signal market. The full product loop:

```
Research Agent publishes signed signal
  → Trading Agent pays for access (x402)
  → Risk Agent verifies before execution
  → Trading Agent requests Uniswap quote and executes on Base Sepolia
  → Validator Agent settles outcome using Uniswap V3 TWAP
  → ERC-8004 ReputationRegistry updated with PnL result
```

Every feature should support at least one step in this loop.

## Skill index — load what you need

### Core loop
- `signal-market-orchestrator` — lifecycle state, agent boundaries, event handoffs
- `signal-validator-spec` — canonical signal schema, TWAP/PnL rules, reputation math
- `signal-signing-and-verification` — EIP-712 signing, identity chain, replay nonce
- `agent-service-scaffolding` — FastAPI shape, middleware, error envelopes, A2A card

### Sponsor integrations
- `x402-and-uniswap` — x402 paid endpoints, Uniswap Trading API quote/swap flow
- `zerog-galileo` — 0G Compute (inference), 0G Storage sidecar, Galileo testnet
- `ens-durin-and-ensip25` — ENS subnames, ENSIP-25 text records, bidirectional verification
- `erc-8004-integration` — IdentityRegistry/ReputationRegistry reads (v1.0 only)

### Contracts and infrastructure
- `contract-deployment-and-verification` — ValidatorSettle.sol, DurinL2Registrar, ABI pinning
- `vps-deployment` — Hetzner Docker Compose, Caddyfile, secrets, OBS setup
- `wallet-and-testnet-ops` — 6 agent wallets, faucets, pre-flight balance checks

### Testing and quality
- `validator-backtest-harness` — offline replay against historical Uniswap V3 data

### Cross-cutting
- `hackathon-compliance` — commit hygiene, AI attribution, FEEDBACK.md, demo video rules
- `engineering-craftsmanship` — reviewable code, naming, commit shape, AI transparency
- `demo-runbook` — 3-minute demo path, sponsor proof, fallback ladder, preflight
- `product-voice-and-agent-personality` — copy, agent personalities, narration tone
- `sibylfi-design-system` — Oracle Cyberpunk palette, typography, sigils, card pattern

## Git policy

- **Never run `git push`** or any command that updates a remote.
- **Never merge to `main`** unless the human explicitly asks.
- **Local commits only when asked.** The human pushes to `main`.
- Do not include `.env`, private keys, or secrets in any commit.
- Commit messages use the pattern `scope: description`, e.g.
  `trading: add quote freshness check`.

## AI attribution

When AI assists with code or docs, note it in `AI_USAGE.md`. Save important
prompts or prompt summaries in `specs/prompts/`. Keep attribution honest; the
hackathon requires visible team contribution alongside AI assistance.
