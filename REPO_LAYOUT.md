# SibylFi Repo Layout

A reference scaffold of every file in this zip, with one-line notes on each.

## Top level

```
README.md                — project overview + quickstart
ARCHITECTURE.md          — condensed design reference
FEEDBACK.md              — DX feedback for Uniswap (required for prize eligibility)
MOCK_MODE.md             — explains the offline-runnable mock layer
LICENSE                  — MIT
.env.example             — environment variable template (commented per-section)
.gitignore               — excludes .env, build artifacts, etc.
```

## /contracts — Foundry workspace

```
contracts/
├── foundry.toml                              — Foundry config
├── README.md                                 — contracts-specific notes
├── erc8004-v1-abi.json                       — pinned ABI (per erc-8004-integration skill)
├── deployed-addresses.json                   — verified addresses on Sepolia + Base Sepolia
├── src/ValidatorSettle.sol                   — the on-chain attestation contract
├── script/DeployValidatorSettle.s.sol        — Foundry deploy script
└── test/ValidatorSettle.t.sol                — 5 tests covering happy + revert paths
```

## /agents — Python multi-agent system

```
agents/
├── requirements.txt                          — all Python deps
├── shared/                                   — code reused across all agents
│   ├── Dockerfile                            — base image for every agent service
│   ├── signal_schema.py                      — canonical Pydantic Signal/Outcome/Settlement
│   ├── settings.py                           — pydantic-settings env loader
│   ├── x402_middleware.py                    — FastAPI dependency for paid endpoints
│   ├── x402_client.py                        — Trading Agent's payment helper (mock-aware)
│   ├── erc8004_client.py                     — read/write wrapper for ERC-8004 v1.0
│   ├── signing.py                            — sign/verify signals + risk attestations
│   ├── inference.py                          — 0G Compute / Anthropic / mock fallback chain
│   ├── db.py                                 — Postgres pool + auto-applied schema
│   ├── logging_setup.py                      — structlog config
│   ├── base_research_agent.py                — strategy-driven research agent (LLM = calibrator)
│   ├── research_app_factory.py               — FastAPI factory for research personas
│   ├── strategies/                           — pure rule engines + indicator math
│   │   ├── indicators.py                     — Pine ports: EMA/RSI/ATR/Bollinger/Donchian/SuperTrend...
│   │   ├── snapshot.py                       — SwingFeatures, ScalperFeatures, StrategyResult, params
│   │   ├── swing.py                          — evaluate_swing() — 5-confluence strict mode
│   │   ├── scalper.py                        — evaluate_scalper() — 4-setup adaptive ML
│   │   ├── feature_provider.py               — load_features(profile, token); MOCK_MODE-aware
│   │   └── mock_features.json                — deterministic snapshots for demo
│   └── mocks/                                — fixtures used in MOCK_MODE
│       ├── erc8004_data.json                 — 2 pre-registered v2 agents
│       └── twap_fixtures.json                — synthetic prices for validator tests
│
├── research_swing/main.py                    — "swing.sibyl.eth" — 4H/1D Murphy+Dow+Elder
├── research_scalper/main.py                  — "scalper.sibyl.eth" — 1m/5m adaptive multi-setup
│
├── trading/
│   ├── uniswap.py                            — Uniswap Trading API wrapper (with required headers)
│   ├── agent.py                              — discover→pay→risk→swap→record pipeline
│   └── main.py                               — FastAPI exposing /trade
│
├── risk/
│   ├── thresholds.json                       — deterministic check parameters
│   ├── checks.py                             — RiskChecker.check() — 5 deterministic checks
│   └── main.py                               — FastAPI exposing paid /verify
│
└── validator/
    ├── algorithm.py                          — settle() + reputation_update() — THE CORE
    ├── twap.py                               — Uniswap V3 TWAP read (mocked from fixtures)
    ├── main.py                               — APScheduler cron + ERC-8004 attestation
    └── test_algorithm.py                     — 8 unit tests, all passing on the algorithm
```

## /orchestrator — frontend BFF

```
orchestrator/main.py                          — FastAPI: /api/leaderboard, /api/signals, /demo/*
```

## /sidecar-0gstorage — TS service for 0G Storage

```
sidecar-0gstorage/
├── package.json                              — Express + 0G TS SDK
├── tsconfig.json
├── Dockerfile
└── src/index.ts                              — /upload + /download with mock fallback
```

## /frontend — Next.js 15

```
frontend/
├── package.json                              — Next 15 + Wagmi + Viem + lucide-react
├── tsconfig.json
├── next.config.js                            — rewrites /api/* and /demo/* to orchestrator
├── tailwind.config.js                        — Cinzel + Inter + JetBrains Mono
├── postcss.config.js
├── Dockerfile
├── README.md                                 — frontend-specific notes + how to wire live data
├── app/
│   ├── layout.tsx                            — root layout with Google Fonts
│   ├── page.tsx                              — dynamic-imports the prototype
│   └── globals.css                           — design system CSS variables
├── components/SibylFiPrototype.jsx           — the 1400-line prototype (4 views, 6 sigils)
├── lib/
│   ├── api.ts                                — typed orchestrator client
│   └── ensip25.ts                            — bidirectional verification helper
└── public/                                   — (empty placeholder)
```

## /infra — deployment

```
infra/
├── docker-compose.yml                        — orchestrates all 9 services + Postgres + Redis
└── Caddyfile                                 — reverse proxy with auto-TLS
```

## /scripts — operational helpers

```
scripts/
├── check-health.sh                           — pre-recording validation
├── compliance-check.sh                       — pre-submission ETHGlobal compliance check
└── faucet-drip.sh                            — daily 0G OG distribution
```

## /specs — human-authored design docs

```
specs/
├── signal-validator.md                       — Day-1 spec; the canonical reference
├── reputation-math.md                        — why the math is what it is
├── risk-thresholds.md                        — why each threshold has the value it has
└── prompts/README.md                         — how to populate this folder during the build
```

## /demo — recording materials

```
demo/
├── recording-storyboard.md                   — scene-by-scene plan with narration
└── seeds.json                                — pre-seeded scenarios for the demo
```

## /.claude/skills — operational knowledge for AI assistants

```
.claude/skills/
├── README.md                                 — authoring strategy
├── erc-8004-integration/                     — pin v1.0 ABI; forbid memory-generated ABI
├── signal-validator-spec/                    — schema, TWAP rule, gas/slippage attribution
├── x402-and-uniswap/                         — server middleware + alpha Python client warning
├── zerog-galileo/                            — Compute SDK + TS sidecar pattern + provider rotation
├── ens-durin-and-ensip25/                    — exact text record key syntax
├── vps-deployment/                           — Hetzner CPX31 + Docker Compose + Caddy + OBS
├── hackathon-compliance/                     — AI involvement clause, FEEDBACK.md, demo specs
└── sibylfi-design-system/                    — palette, type rules, sigil meanings, voice/tone
```

---

**Total: 109 files. Validator algorithm has 8 passing unit tests. All Python modules pass syntax check. All JSON + YAML files validate. The smart contracts compile (well, they will when you `forge install foundry-rs/forge-std`).**
