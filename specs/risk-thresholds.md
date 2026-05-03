# Risk Thresholds — rationale

> **Authored by:** Trader (initials __)
> **Cross-reference:** `agents/risk/thresholds.json` (the source of truth)

The Risk Agent is deterministic by design. No ML, no probability scores — five hard checks, pass or fail. This document explains why each threshold has the value it has.

## 1. `max_capital_pct_of_pool_tvl: 0.05`

**5% of pool TVL maximum.**

Rationale: at 5% capital deployment, expected price impact in a Uniswap V3 pool is typically under 30 bps for a well-routed swap. Above 5%, you start moving the price meaningfully — which means the trader is now competing with their own signal, and the signal's TWAP-based settlement becomes inaccurate.

A more conservative version would be 2% but in a hackathon demo with low TVL pools, 5% lets demo traffic actually go through.

## 2. `max_slippage_bps: 25`

**0.25% slippage cap.**

Rationale: signals that need < 25 bps slippage to be profitable are healthy. Signals where the expected slippage *already* equals the expected target percentage are not worth executing. Setting the cap at 25 bps eliminates the bottom 80% of "alpha" that's actually just noise within the spread.

## 3. `max_volatility_atr_multiple: 4.0`

**Reject if 24h ATR is more than 4× the 30d-average ATR.**

Rationale: when a token is in an ATR spike (news event, exploit, depeg, exchange listing), the historical TWAP becomes a poor reference for "what should the price be." Settlement against TWAP in those moments is unreliable. Better to skip the trade than settle against potentially bogus reference data.

## 4. `min_pool_tvl_usd: 10000`

**$10k minimum pool TVL.**

Rationale: below $10k, even tiny trades cause large price impact AND TWAP manipulation costs are trivial (< $100). Manipulation-resistant settlement requires meaningful liquidity.

In the master document we had $10k as the floor; we keep it. If we see legitimate demand for thinner-pool signals during the build, we can lower it — but the v0 default is $10k.

## 5. Self-purchase (no threshold; binary)

**Reject if `buyer_addr == publisher_addr`.**

Rationale: single most common gaming attack vector. Catch it at the Risk Agent layer (in addition to the x402 facilitator) so we have defense-in-depth.

## What's NOT in the Risk Agent

These checks were considered but rejected:

- **Confidence threshold.** We considered "reject if confidence_bps < 5000" but rejected — confidence is the publisher's claim, not a Risk Agent fact. The Validator's reputation math already handles low-confidence signals (low-confidence + bad outcome = bigger reputation hit relative to claim).

- **Token blocklist.** Considered "reject known scam tokens" but the maintenance burden + edge cases (legitimate fork tokens) make this a v2 thing.

- **Direction sanity check.** Considered "reject SHORT signals on stable pairs" — but this is the Trader's job to decide whether to act on, not the Risk Agent's job to forbid.

- **Cross-signal correlation.** Considered "reject if same buyer is acting on conflicting signals from same publisher" but this requires global state across calls, which the deterministic Risk Agent design forbids.

## When to update these thresholds

If a team member proposes a threshold change during the build:
1. They propose a number AND a rationale (one or two sentences)
2. Both Trader and Data Scientist sign off (since these affect both signal quality and validator math)
3. Update `agents/risk/thresholds.json` (operational)
4. Update this file (rationale)
5. Note the change in the relevant `/specs/prompts/` doc if AI is involved

Don't tune thresholds based on a single failing demo run. Demo failures are usually configuration issues, not threshold issues.
