# AI Usage

SibylFi was built during the ETHGlobal Open Agents hackathon with AI tools as
implementation assistants. The product concept, sponsor selection, strategy
direction, contract boundaries, risk thresholds, deployment decisions, and
all final review and testing were authored by the human team. AI accelerated
implementation; it did not own product or security decisions.

Tools used: **Claude (Opus and Sonnet) via Claude Code** and **OpenAI Codex /
ChatGPT (GPT-4-class)**.

---

## Authored by humans, no AI assistance

These artifacts and decisions are entirely human work. AI did not draft or
edit them.

- **Product concept** — the Signal Market lifecycle, the choice to settle
  reputation via on-chain TWAP rather than self-reported PnL, and the decision
  to gate every read with x402.
- **Sponsor selection and integration plan** — which sponsors to target
  (0G, Uniswap, ENS, ERC-8004, x402), how each fits the loop, and the
  trade-offs documented in [`FEEDBACK.md`](FEEDBACK.md).
- **Risk thresholds and strategy parameters** — the 12 deterministic risk
  checks, the appetite-profile cutoffs, the strategy confluence rules, and
  the LLM confidence-delta clamp (±1000 bps) in [`specs/`](specs/).
- **Validator settlement math and reputation algorithm** — TWAP window
  selection, gas/slippage attribution rules, and the reputation update
  formula in [`specs/`](specs/).
- **Demo seed scenarios** — [`demo/seeds.json`](demo/seeds.json), the
  reproducible agent fixtures the orchestrator's `/demo/*` endpoints
  drive the recording from.
- **Visual identity** — the Oracle Cyberpunk concept, the six agent sigils,
  persona-color mapping, and the design-system rules in
  [`.claude/skills/sibylfi-design-system/SKILL.md`](.claude/skills/sibylfi-design-system/SKILL.md).
- **All testnet operations** — wallet creation and funding, contract
  deployments, ABI pinning, transaction submission, and the live demo run.
- **Sponsor DX feedback** — [`FEEDBACK.md`](FEEDBACK.md) was authored by
  the team member who actually integrated the Uniswap Trading API, based
  on hands-on debugging notes, not generated.

---

## Documentation

- Files assisted: `README.md`, `ARCHITECTURE.md`, `REPO_LAYOUT.md`,
  `demo/MOCK_MODE.md`, `specs/*.md`, `frontend/README.md`,
  `contracts/README.md`.
- AI role: Structuring sections, tightening prose, generating Mermaid
  diagrams from human-described topology, and producing tables from
  human-supplied lists.
- Human role: All architectural decisions, system topology, and the actual
  facts in every doc. The team reviewed every claim against the running code.

## Agent services

- Files assisted: `agents/shared/*`, `agents/research_swing/*`,
  `agents/research_scalper/*`, `agents/risk/*`, `agents/trading/*`,
  `agents/validator/*`.
- AI role: Scaffolding FastAPI services, Pydantic schemas, signing helpers,
  the Uniswap client, and unit-test skeletons. AI translated human-specified
  rules (e.g. "reject if signal age > 5 minutes") into Python.
- Human role: Defined every agent boundary, the signal lifecycle state
  machine, the 12 risk checks and their thresholds, the strategy parameters,
  and the validator's PnL math. Humans ran every test and verified behavior
  end-to-end — AI-generated tests were re-read and corrected before being
  trusted.

## Frontend

- Files assisted: `frontend/components/*`, `frontend/app/*`,
  `frontend/lib/*`, `frontend/README.md`.
- AI role: Implemented React components, Tailwind styles, and animation
  details against a human-defined design system. Helped polish the
  leaderboard, signal feed, Rite flow, Forge page, wallet UI, and ENS
  verification states.
- Human role: Owned the Oracle Cyberpunk visual identity, the four-view
  IA (Leaderboard / Signals / Rite / Forge), the demo flow, and all UX
  priorities. Final UI review and the design-system rules were human work.

## Smart contracts

- Files assisted: `contracts/src/ValidatorSettle.sol`,
  `contracts/src/SibylFiRegistrar.sol`, `contracts/script/*`,
  `contracts/test/*`.
- AI role: Drafted boilerplate (event definitions, OpenZeppelin imports,
  Foundry script structure) and produced first-pass test cases against
  human-specified invariants.
- Human role: Specified the on-chain responsibilities (what each contract
  must and must not do), wrote the access-control rules, designed the
  settlement event schema, controlled all private keys and deployments,
  and verified contract bytecode on Basescan after deploy. Every line of
  the deployed contracts was read and approved by a human before
  `forge create` ran.

## Sponsor integrations

- Files assisted: `agents/shared/x402_*`, `agents/trading/uniswap.py`,
  `agents/validator/*twap*`, `sidecar-0gstorage/*`,
  `agents/shared/erc8004_client.py`.
- AI role: Wired up x402 payment handling, Uniswap quote/swap calls,
  Uniswap V3 TWAP reads for settlement, ERC-8004 v1.0 lookups, and the
  0G Storage TypeScript sidecar.
- Human role: Obtained API keys, funded all six agent wallets across
  three testnets, verified each integration against official sponsor docs
  (not training data), ran live transactions, and chose the fallback
  behavior that keeps the demo reliable. The team verified that ERC-8004
  v1.0 addresses were used (not v0.4) after Codex initially produced
  v0.4-shaped code from training data.

## Debugging and deployment

- AI role: Helped diagnose `desktop.ini` Git metadata noise, Docker and
  TypeScript build failures, branch divergence, rebase conflicts, and
  commit splitting.
- Human role: Performed every push, every VPS pull, every deployment,
  every testnet transaction, and every demo dry-run. AI did not have
  credentials.

## 0G Storage sidecar deploy fix

- Files assisted: `sidecar-0gstorage/package.json`,
  `sidecar-0gstorage/tsconfig.json`, `sidecar-0gstorage/src/index.ts`.
- AI role: Codex diagnosed the TypeScript module-resolution failure and
  proposed the migration to the current official 0G Storage TypeScript
  SDK package.
- Human role: Reported the deployment error, reviewed the SDK package
  change against the live 0G docs, rebuilt the sidecar image, and ran the
  end-to-end demo path against Galileo before merging.
