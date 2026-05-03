# SibylFi Contracts

Foundry workspace for the contracts SibylFi deploys.

## What we deploy

- **`ValidatorSettle.sol`** (Base Sepolia, ~150 lines including comments) — the
  Validator Agent posts `SignalSettled` events here. Reputation updates on
  ERC-8004 are a separate transaction from the same wallet.

## What we read but don't deploy

- ERC-8004 IdentityRegistry v1.0 (Sepolia) — pinned ABI in `erc8004-v1-abi.json`
- ERC-8004 ReputationRegistry v1.0 (Sepolia) — same file
- Uniswap Universal Router v2 (Base Sepolia) — accessed via Trading API only
- ENS Durin L2 Registrar — deployed via `durin.dev`, not Foundry

## Build and test

```bash
forge install foundry-rs/forge-std
forge build
forge test -vv
```

## Deploy

```bash
# Set VALIDATOR_WALLET in .env first
forge script script/DeployValidatorSettle.s.sol \
  --rpc-url $BASE_SEPOLIA_RPC \
  --broadcast \
  --verify
```

Update `deployed-addresses.json` with the returned address.

## Verifying ERC-8004 addresses

The pinned addresses in `deployed-addresses.json` are checked into the repo
based on the v1.0 launch announcement. **Before any real-network use, verify
them on the live Sepolia block explorer.** The v0.4 → v1.0 migration was a
breaking change and outdated documentation may circulate. The
`erc-8004-integration` skill in `.claude/skills/` enforces this.

## Why no ENS Durin contracts here

Durin's deployment flow is:

1. Visit `durin.dev`, fill in form (parent name = `sibyl.eth`, L2 = Base Sepolia)
2. Download generated Foundry script
3. Deploy from your machine
4. Call `addRegistrar(deployedAddr)` on the parent ENS resolver from owner wallet

Since the script is auto-generated per deployment, we don't check it into our
contracts folder. If you do deploy, save the resulting `Deploy.s.sol` to
`contracts/durin/` for reference.
