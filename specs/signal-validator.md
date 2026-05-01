# signal-validator.md
# SibylFi Signal Market — Validator Algorithm Specification
**Version:** 1.0 — LOCKED before Validator code is written  
**Owner:** Data Scientist  
**Status:** Ready for Smart Contract + DevOps integration  
**Hackathon:** ETHGlobal Open Agents — 0G + ENS + Uniswap

---

## 1. TWAP Window Methodology

### 1.1 Source
Uniswap V3 on-chain TWAP oracle via `IUniswapV3Pool.observe()`.  
- Pool: WETH/USDC 0.05% on Base Sepolia  
- Function: `observe(uint32[] secondsAgos)` returns `(int56[] tickCumulatives, uint160[] secondsPerLiquidityCumulativeX128s)`  
- TWAP derivation:

```python
tick_twap = (tickCumulative_end - tickCumulative_start) / window_seconds
price_twap = 1.0001 ** tick_twap  # token1/token0 price
```

### 1.2 Window Sizes

| Purpose | Window | Rationale |
|---|---|---|
| `reference_price` at signal publication | 1800 s (30 min) | Balances recency vs manipulation resistance (Murphy: no ruido de spot) |
| Settlement evaluation (horizon end) | 1800 s (30 min) | Consistent with publication reference |
| `twap_min_in_window` for stop evaluation | Full `horizon_seconds` | Elder: stop vs TWAP, not vs wick |

**Rule:** All price references in the system use TWAP₃₀ₘ. Spot price is never used for settlement decisions.

### 1.3 Manipulation Defenses

Based on Uniswap V3 TWAP oracle research (Euler/ChaoS):

| Attack vector | Defense |
|---|---|
| Single-block wick | 30-min TWAP absorbs it (1 block / 1800 blocks weight = 0.055%) |
| Multi-block sandwich | Cost of sustained manipulation = `blocks_needed × gas × price_impact`; economically infeasible on Base at current liquidity |
| Low-liquidity pool | Hard requirement: pool TVL ≥ $100K in the directional side at publication time |
| Oracle cardinality | Validator verifies `pool.slot0().observationCardinality ≥ 100` before accepting any signal |

```python
# Validator pre-check
assert pool.slot0().observationCardinality >= 100, "Oracle cardinality insufficient"
assert pool_tvl_directional >= 100_000, "Insufficient liquidity for manipulation defense"

deviation = abs(spot_price - twap_30m) / twap_30m
assert deviation <= 0.03, "Spot/TWAP deviation > 3% — possible active manipulation"
```

---

## 2. Entry-Price Reference Rule

### 2.1 Decision: Publication-Time TWAP (not execution-time)

**Rule:** `reference_price` = TWAP₃₀ₘ at the block the signal is published (`published_at_block`).

**Rationale:**
- The Research Agent has no control over execution timing or slippage — those belong to the Trading Agent.
- Using execution price would penalize the Research Agent for execution quality it doesn't own.
- Murphy: "El mercado lo descuenta todo" — the signal encodes a thesis about future price movement from a known current price.

### 2.2 Implementation

```python
# At signal publication (Research Agent)
reference_price = get_twap(pool, window=1800, at_block=current_block)
signal.reference_price = reference_price
signal.published_at_block = current_block

# At settlement (Validator Agent)
# Re-derive the reference price from the chain — do NOT trust the signal's declared value
verified_reference = get_twap(pool, window=1800, at_block=signal.published_at_block)

# Sanity check: declared vs on-chain reference
assert abs(verified_reference - signal.reference_price) / verified_reference < 0.001, \
    "Reference price mismatch > 0.1% — signal may be fraudulent"
```

### 2.3 Execution-Price Isolation

The Trading Agent records `execution_price` separately. The gap `(execution_price - reference_price)` is entirely attributed to execution quality (slippage) — never subtracted from the Research Agent's signal evaluation.

---

## 3. Gas-Adjusted PnL Methodology

### 3.1 Accounting Model

PnL is computed from the **Research Agent's signal quality perspective**, not the Trading Agent's actual P&L.

```
gross_pnl_bps = (exit_price - reference_price) / reference_price × 10000  [for long]
gross_pnl_bps = (reference_price - exit_price) / reference_price × 10000  [for short]

net_pnl_bps = gross_pnl_bps - gas_cost_bps - slippage_cost_bps
```

### 3.2 Whose Gas

**Gas accounted:** Validator Agent's gas cost for the settlement transaction + Trading Agent's swap gas.  
**Not accounted:** Research Agent's publication gas (signal quality metric, not execution).

| Gas item | Counted in PnL? | Rationale |
|---|---|---|
| Trading Agent swap execution | Yes | Cost of acting on the signal |
| Risk Agent verification call | Yes (small) | Part of acting on the signal |
| Validator settlement tx | No | Infrastructure cost, not signal cost |
| Research Agent publication | No | Fixed overhead, not signal quality |

### 3.3 ETH/USD Reference Rate

```python
# Source: Chainlink ETH/USD on Base Sepolia
# Feed: 0x4aDC67696bA383F43DD60A9e78F2C97Fbbfc7cb1 (Base Sepolia)
# Updated: every 0.5% deviation or 1 hour

eth_usd = chainlink_feed.latestRoundData().answer / 1e8  # 8 decimals

# Gas cost in USD
gas_cost_usd = gas_used × gas_price_wei × eth_usd / 1e18

# Convert to bps relative to position size
# position_size_usd = position_size_units × reference_price
gas_cost_bps = (gas_cost_usd / position_size_usd) * 10000
```

### 3.4 Gas Cap (Testnet Protection)

On Base Sepolia, gas costs can be anomalously low. Cap gas deduction:

```python
gas_cost_bps = min(gas_cost_bps, 50)  # max 50 bps = 0.5% deduction from gas
```

---

## 4. Slippage Attribution Model

### 4.1 Split: Signal Quality vs Execution Quality

```
total_slippage_bps = (execution_price - reference_price) / reference_price × 10000  [long]

signal_quality_slippage = deviation at publication (spot - TWAP) / TWAP × 10000
execution_quality_slippage = total_slippage_bps - signal_quality_slippage
```

| Slippage component | Owner | Impact on reputation |
|---|---|---|
| `signal_quality_slippage` | Research Agent | **Yes** — penalizes publishing when spot ≠ TWAP |
| `execution_quality_slippage` | Trading Agent | **No** — does not affect Research Agent reputation |

### 4.2 Implementation

```python
# Computed at settlement time
spot_at_publication = get_spot(block=signal.published_at_block)  # from tx logs
twap_at_publication = signal.reference_price  # verified on-chain (section 2)

# Signal quality component (Research Agent responsibility)
signal_slippage_bps = abs(spot_at_publication - twap_at_publication) / twap_at_publication * 10000

# Total observed slippage
exec_price = trading_agent.execution_price  # recorded in Postgres at execution time
total_slippage_bps = abs(exec_price - twap_at_publication) / twap_at_publication * 10000

# Execution quality (not charged to Research Agent)
exec_slippage_bps = max(0, total_slippage_bps - signal_slippage_bps)

# Only signal_slippage_bps enters the net_pnl_bps computation
net_pnl_bps = gross_pnl_bps - gas_cost_bps - signal_slippage_bps
```

---

## 5. Validator Algorithm Pseudocode

```python
# ═══════════════════════════════════════════════════════════════
# VALIDATOR AGENT — Settlement Algorithm v1.0
# Runs every 60 seconds (APScheduler cron)
# ═══════════════════════════════════════════════════════════════

def settlement_loop():
    pending = postgres.query(
        "SELECT * FROM signals WHERE status='pending' AND published_at + horizon_seconds < NOW()"
    )
    for signal in pending:
        result = settle_signal(signal)
        post_to_chain(signal, result)
        update_postgres(signal, result)


def settle_signal(signal: Signal) -> SettlementResult:
    """
    Deterministic settlement. No randomness. No side effects on price.
    Returns one of: WIN | LOSS | EXPIRED | INCONCLUSIVE | INVALID
    """

    # ── STEP 1: Verify oracle cardinality ──────────────────────
    pool = get_pool(signal.token)
    if pool.slot0().observationCardinality < 100:
        return SettlementResult(outcome=INCONCLUSIVE, reason="low_cardinality", rep_delta=0)

    # ── STEP 2: Verify reference price ─────────────────────────
    verified_ref = get_twap(pool, window=1800, at_block=signal.published_at_block)
    if abs(verified_ref - signal.reference_price) / verified_ref > 0.001:
        return SettlementResult(outcome=INVALID, reason="reference_price_mismatch", rep_delta=-200)

    # ── STEP 3: Collect TWAP checkpoints over horizon ──────────
    horizon_start_block = signal.published_at_block
    horizon_end_block   = signal.published_at_block + (signal.horizon_seconds // 2)  # ~2s/block Base
    
    checkpoints = collect_twap_checkpoints(
        pool, horizon_start_block, horizon_end_block, interval_blocks=15  # ~30s resolution
    )
    
    coverage = len(checkpoints) / expected_checkpoints(signal.horizon_seconds)
    if coverage < 0.80:
        return SettlementResult(outcome=INCONCLUSIVE, reason="insufficient_checkpoints", rep_delta=0)

    # ── STEP 4: Evaluate stop hit (TWAP, not spot) ─────────────
    twap_min = min(c.price for c in checkpoints)
    twap_max = max(c.price for c in checkpoints)
    twap_exit = checkpoints[-1].price  # TWAP at horizon end

    if signal.direction == "long":
        stop_hit    = twap_min <= signal.stop_price
        target_hit  = twap_max >= signal.target_price
    else:  # short
        stop_hit    = twap_max >= signal.stop_price
        target_hit  = twap_min <= signal.target_price

    # ── STEP 5: Determine outcome ───────────────────────────────
    # Stop hit takes precedence over target (conservative, Elder)
    if stop_hit:
        outcome    = OUTCOME.LOSS
        exit_price = signal.stop_price  # assume stop filled at declared level
    elif target_hit:
        outcome    = OUTCOME.WIN
        exit_price = signal.target_price
    else:
        # Horizon expired without hitting either
        outcome    = OUTCOME.EXPIRED
        exit_price = twap_exit

    # ── STEP 6: Compute gas-adjusted PnL ───────────────────────
    if signal.direction == "long":
        gross_pnl_bps = (exit_price - verified_ref) / verified_ref * 10000
    else:
        gross_pnl_bps = (verified_ref - exit_price) / verified_ref * 10000

    eth_usd         = chainlink_eth_usd()
    gas_cost_bps    = min(compute_gas_cost_bps(signal, eth_usd), 50)
    slippage_bps    = compute_signal_slippage_bps(signal)
    net_pnl_bps     = gross_pnl_bps - gas_cost_bps - slippage_bps

    # ── STEP 7: Compute reputation delta ───────────────────────
    rep_delta = compute_rep_delta(signal, outcome, net_pnl_bps)

    return SettlementResult(
        outcome       = outcome,
        exit_price    = exit_price,
        gross_pnl_bps = gross_pnl_bps,
        net_pnl_bps   = net_pnl_bps,
        gas_cost_bps  = gas_cost_bps,
        slippage_bps  = slippage_bps,
        rep_delta     = rep_delta,
        brier_input   = (1 if outcome == WIN else 0, signal.confidence_bps / 10000)
    )


def post_to_chain(signal: Signal, result: SettlementResult):
    """Write to ValidatorSettle.sol + ERC-8004 ReputationRegistry"""
    # 1. Emit SignalSettled on ValidatorSettle (Base Sepolia)
    validator_settle_contract.settle(
        signal_id  = signal.signal_id,
        win        = (result.outcome == WIN),
        pnl_bps    = int(result.net_pnl_bps),
        timestamp  = current_timestamp()
    )
    # 2. Write reputation attestation (Sepolia — ERC-8004)
    reputation_registry.attest(
        agent     = signal.publisher_address,
        score     = rep_delta_to_score(result.rep_delta),
        metadata  = encode_metadata(signal.signal_id, result)
    )
```

---

## 6. Reputation Update Math

### 6.1 Score Structure

```
reputation_score ∈ [0, 10000]  (bps, like confidence_bps)
Initial score for new agent: 5000  (neutral)
```

### 6.2 Per-Signal Rep Delta

```python
def compute_rep_delta(signal, outcome, net_pnl_bps) -> int:
    """
    Returns signed integer in bps to add to reputation score.
    """
    # Base delta: PnL-weighted outcome
    if outcome == WIN:
        base_delta = +100 + max(0, net_pnl_bps * 0.5)   # floor +100, bonus for magnitude
    elif outcome == LOSS:
        base_delta = -150 + min(0, net_pnl_bps * 0.5)   # floor -150, worse for large losses
    elif outcome == EXPIRED:
        base_delta = net_pnl_bps * 0.3                   # small positive/negative for expiry
    elif outcome == INCONCLUSIVE:
        base_delta = 0                                    # no impact (data gap, not agent fault)
    elif outcome == INVALID:
        base_delta = -300                                 # severe: reference price fraud

    # Calibration multiplier (Douglas: Brier Score)
    historical_brier = get_historical_brier(signal.publisher, lookback_signals=20)
    if historical_brier is None:
        calibration_multiplier = 1.0   # insufficient history
    elif historical_brier <= 0.20:
        calibration_multiplier = 1.20  # well-calibrated agent: bonus
    elif historical_brier <= 0.25:
        calibration_multiplier = 1.00  # acceptable
    else:
        calibration_multiplier = 0.70  # poorly calibrated: discount

    # Statistical significance weight (Douglas: N<10 is noise)
    signals_7d = count_signals_7d(signal.publisher)
    significance_weight = min(signals_7d / 10.0, 1.0)  # 0.1 → 1.0

    rep_delta = int(base_delta * calibration_multiplier * significance_weight)

    # Clamp: no single signal can move score more than ±300 bps
    return max(-300, min(300, rep_delta))
```

### 6.3 Rolling Score Update

```python
def update_reputation_score(publisher: str, rep_delta: int) -> int:
    """7-day rolling weighted score. Exponential decay on old signals."""
    signals_7d = get_signals_7d(publisher)  # from 0G Storage

    # Weighted rolling score: recent signals carry more weight
    decay_lambda = 0.1  # per-day decay
    weighted_sum = 0
    weight_total = 0

    for s in signals_7d:
        age_days = (now() - s.settled_at).days
        w = exp(-decay_lambda * age_days)
        weighted_sum += s.net_pnl_bps * w
        weight_total += w

    rolling_roi_bps = weighted_sum / weight_total if weight_total > 0 else 0

    # New score: blend current score with rolling ROI signal
    current_score = reputation_registry.getScore(publisher)
    new_score = current_score + rep_delta

    # Hard bounds
    return max(0, min(10000, new_score))
```

### 6.4 Brier Score Computation

```python
# Brier Score = mean squared error of probability forecasts
# Lower is better. Perfect calibration = 0.0. Random = 0.25.
def compute_brier(signals: List[Signal]) -> float:
    if len(signals) < 5:
        return None  # insufficient data
    sq_errors = [
        (s.confidence_bps / 10000 - (1 if s.outcome == WIN else 0)) ** 2
        for s in signals
        if s.outcome in [WIN, LOSS]  # exclude EXPIRED/INCONCLUSIVE from calibration
    ]
    return sum(sq_errors) / len(sq_errors) if sq_errors else None
```

### 6.5 Anti-Gaming Defenses (in Reputation Math)

| Attack | Defense |
|---|---|
| Spam near-zero signals | `significance_weight` scales with count; <10 signals → max 10% weight |
| Self-purchase wash-trade | `x402` layer: caller ≠ publisher enforced at payment; reputation only updates if ≥1 distinct external buyer |
| Cherry-pick easy signals | Capital-weighting: `rep_delta` multiplied by `log(1 + buyers_count)` if buyer data available |
| Confidence inflation | Brier Score `calibration_multiplier` penalizes overconfident agents |

---

## 7. Outcome Types Reference

| Outcome | Condition | Rep Impact |
|---|---|---|
| `WIN` | TWAP reaches `target_price` before `stop_price` within horizon | Positive |
| `LOSS` | TWAP reaches `stop_price` before `target_price` within horizon | Negative |
| `EXPIRED` | Horizon ends, neither target nor stop reached | Small ± based on net_pnl at expiry |
| `INCONCLUSIVE` | <80% TWAP checkpoints or oracle cardinality issue | Zero |
| `INVALID` | Reference price mismatch >0.1% | Large negative (-300) |

---

## 8. Schema (Locked)

```json
{
  "signal_id": "0x<keccak256(publisher + token + published_at_block)>",
  "publisher": "research-meanrev.signalmarket.eth",
  "publisher_address": "0x...",
  "token": "eip155:84532/erc20:0x...USDC",
  "direction": "long",
  "reference_price": 3450.21,
  "target_price": 3485.00,
  "stop_price": 3430.00,
  "horizon_seconds": 3600,
  "confidence_bps": 6500,
  "published_at_block": 12345678,
  "signature": "0x..."
}
```

**Derived at settlement (not in signal):**
- `verified_reference_price` (re-derived from chain)
- `net_pnl_bps`
- `outcome`
- `rep_delta`

---

*Locked: Data Scientist — SibylFi Signal Market — ETHGlobal Open Agents Hackathon*
