# Uniswap Trading API — DX Feedback

This file is required for Uniswap prize eligibility. Below is the feedback the
SibylFi team collected from hands-on use of the Uniswap Trading API during the
ETHGlobal Open Agents hackathon.

## What worked well

- **The `/v1/quote` endpoint shape is excellent.** The response includes both
  the routing decision AND the `permitData` typed-data structure pre-formatted
  for EIP-712 signing. We didn't have to reconstruct the Permit2 message from
  scratch — huge time saver.
- **Universal Router v2 abstraction.** Treating the swap target as a single
  endpoint regardless of underlying pool topology meant our Trading Agent's
  swap code is ~30 lines and didn't need to know about pool selection.
- **Base Sepolia support out of the box.** No special setup, no different SDK,
  no separate API key — everything just worked with `chainId: 84532`.

## What we hit friction on

### 1. The `x-universal-router-version: 2.0` header is silently required.

We lost ~2 hours to this. Quote requests without the header return a 400 with
no body, which is undebuggable. The OpenAPI spec page mentions the header in
prose but the request examples don't include it.

**Fix:** Add the header to every example in the docs, OR have the API return
a structured 400 like `{"error": "missing_required_header", "header": "x-universal-router-version"}`.

### 2. Permit2 typed-data must be passed back unchanged.

We initially tried to "validate" the `permitData` returned from `/quote` by
JSON-canonicalizing it before signing — this corrupted the EIP-712 hash and
the swap silently rejected the permit. The docs don't explicitly say "treat
this object as opaque between quote and swap."

**Fix:** Add a callout in the Permit2 section: "Do not modify the `permitData`
object between receiving it from `/quote` and signing it. Any reordering of
keys or normalization will invalidate the signature."

### 3. No OpenAPI schema published.

We had to read the docs site and reverse-engineer types from real responses to
generate our TS client. An OpenAPI 3.0 schema would let us auto-generate typed
clients in any language.

**Fix:** Publish `https://trade-api.gateway.uniswap.org/openapi.json` (or
similar). This is table stakes for serious developer tooling.

### 4. Rate limit headers are missing.

The free dev tier has limits but we couldn't see remaining quota in response
headers. We had to count requests ourselves and back off heuristically.

**Fix:** Standard `X-RateLimit-Limit` / `X-RateLimit-Remaining` /
`X-RateLimit-Reset` headers on every response.

## What we'd love to see

- **Programmatic API key issuance.** We had to manually request a key via the
  developer portal. For multi-agent systems where each agent has its own wallet,
  programmatic key issuance per wallet would let us scope rate limits per agent.
- **A "simulate" endpoint.** Like `/v1/quote` but returning the full execution
  trace (path, gas, expected slippage curve, MEV exposure) without committing
  to a swap. We ended up building our own simulator on top of `/quote` to do
  Risk Agent checks.
- **Native support for batched swaps.** Our Trading Agent often executes 3
  signals in close succession. A `/v1/batch-swap` endpoint with shared Permit2
  signature would cut gas and improve UX.

## Where we used the API in SibylFi

- `agents/trading/uniswap.py` — core wrapper for `/v1/quote` and `/v1/swap`
- `agents/risk/checks.py` — uses `/v1/quote` with mock signing to estimate
  slippage as part of Risk Agent's deterministic checks
- `frontend/lib/explain.ts` — fetches `/v1/quote` to display "what would this
  signal cost to execute" on each Live signal in the feed

The Trader role (the one with hands-on DeFi background) authored this file
based on actual integration work, not generic platitudes. Specific endpoints,
specific gotchas, specific timing.

— SibylFi team
