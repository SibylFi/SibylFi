# agent-validator.md
# Validator Agent
**Tipo:** Servicio de settlement determinista (cron + FastAPI /status)  
**Misión:** Decidir, post-horizon, si una señal fue WIN, LOSS, EXPIRED, INCONCLUSIVE, INVALID, o WIN_PARTIAL (multi-TP). Computar PnL ajustado por gas y slippage. Postear attestación a ERC-8004 ReputationRegistry.  
**Frameworks dominantes:** Determinismo absoluto + Brier Score + Sharpe Ratio + Elder (TWAP integrity) + Douglas (significancia)  
**Soporta:** Swing (multi-TP) + Scalper (single TP + trailing) con outcomes diferenciados

---

## 1. Identidad y Misión

Eres el **árbitro determinista** del Signal Market. Cualquier persona puede correr tu algoritmo independientemente y obtener exactamente el mismo resultado.

Cada minuto, revisas señales pendientes cuyo `horizon` expiró. Para cada una:
1. Lees TWAP del oracle de Uniswap V3
2. Detectas el perfil (swing/scalper) y aplicas lógica de outcome correspondiente
3. Computas PnL gross
4. Deduces gas y attribution de slippage
5. Decides outcome (incluyendo `WIN_PARTIAL` para multi-TP)
6. Computas reputation delta
7. Posteas attestación a ERC-8004 (Sepolia) y emite `SignalSettled` (Base Sepolia)

---

## 2. Detección de Perfil

```python
def detect_profile(signal: Signal) -> str:
    if signal.horizon_seconds <= 7200:
        return "scalper"
    elif signal.horizon_seconds >= 86400:
        return "swing"
    else:
        return "intraday"
```

---

## 3. TWAP Methodology

### 3.1 Fuente
Uniswap V3 on-chain TWAP via `IUniswapV3Pool.observe()`.

```python
def get_twap(pool, window_seconds: int, at_block: int = None) -> float:
    secondsAgos = [window_seconds, 0]
    tickCumulatives, _ = pool.observe(secondsAgos, block=at_block)
    tick_diff = tickCumulatives[1] - tickCumulatives[0]
    avg_tick = tick_diff / window_seconds
    return 1.0001 ** avg_tick
```

### 3.2 Ventanas TWAP por perfil

| Propósito | Swing | Scalper |
|---|---|---|
| `reference_price` (publicación) | 1800s (30 min) | **600s (10 min)** |
| Settlement TWAP | 1800s (30 min) | **600s (10 min)** |
| Intervalo checkpoints | 60s (1 min) | **15s** |

```python
def get_twap_window(profile: str) -> int:
    return 600 if profile == "scalper" else 1800

def get_checkpoint_interval(profile: str) -> int:
    return 15 if profile == "scalper" else 60
```

### 3.3 Defensas anti-manipulación

```python
def pre_check_oracle(pool, profile):
    obs_card = pool.slot0().observationCardinality
    if obs_card < 100:
        raise InconclusiveError('low_cardinality')

    tvl = pool.tvl_directional(direction)
    if tvl < 100_000:
        raise InconclusiveError('insufficient_liquidity')

    spot = pool.spot_price()
    twap_30m = get_twap(pool, 1800)
    max_dev = 0.015 if profile == "scalper" else 0.030
    if abs(spot - twap_30m) / twap_30m > max_dev:
        raise InconclusiveError('spot_twap_divergence')
```

---

## 4. Outcomes (incluye WIN_PARTIAL)

| Outcome | Condición | Rep impact |
|---|---|---|
| `WIN` | TWAP alcanza target final antes que stop | Positivo (max) |
| `WIN_PARTIAL` | TWAP alcanza TP1, luego stop hit (BE o original) | Positivo medio |
| `LOSS` | TWAP alcanza stop antes que cualquier TP | Negativo |
| `EXPIRED` | Horizon termina sin alcanzar TP/stop | ± según net_pnl |
| `INCONCLUSIVE` | <80% checkpoints o cardinality issue | Zero |
| `INVALID` | Reference price mismatch >0.1% | -300 (severo) |

---

## 5. Algoritmo de Settlement

```python
def settle_signal(signal: Signal) -> SettlementResult:
    profile = detect_profile(signal)
    pool = get_pool(signal.token)

    # ── STEP 1: Oracle pre-check ───────────────────────────────
    if pool.slot0().observationCardinality < 100:
        return SettlementResult(outcome=INCONCLUSIVE, rep_delta=0)

    # ── STEP 2: Verify reference_price ─────────────────────────
    twap_window = get_twap_window(profile)
    verified_ref = get_twap(pool, twap_window, at_block=signal.published_at_block)
    if abs(verified_ref - signal.reference_price) / verified_ref > 0.001:
        return SettlementResult(outcome=INVALID, rep_delta=-300)

    # ── STEP 3: Collect TWAP checkpoints over horizon ──────────
    horizon_blocks = signal.horizon_seconds // 2   # ~2s/block Base
    interval = get_checkpoint_interval(profile)
    checkpoints = collect_twap_checkpoints(
        pool,
        from_block=signal.published_at_block,
        to_block=signal.published_at_block + horizon_blocks,
        interval_seconds=interval
    )

    expected = signal.horizon_seconds // interval
    coverage = len(checkpoints) / expected
    if coverage < 0.80:
        return SettlementResult(outcome=INCONCLUSIVE, rep_delta=0)

    # ── STEP 4: Outcome logic ──────────────────────────────────
    has_multi_tp = signal.metadata.get("tp1") is not None and profile == "swing"

    if has_multi_tp:
        result = settle_multi_tp(signal, checkpoints, verified_ref)
    else:
        result = settle_single_tp(signal, checkpoints, verified_ref, profile)

    # ── STEP 5: Gas-adjusted PnL ───────────────────────────────
    eth_usd = chainlink_eth_usd()
    gas_cost_bps = min(compute_gas_cost_bps(signal, eth_usd), 50)
    slippage_bps = compute_signal_slippage_bps(signal)
    result.net_pnl_bps = result.gross_pnl_bps - gas_cost_bps - slippage_bps
    result.gas_cost_bps = gas_cost_bps
    result.slippage_bps = slippage_bps

    # ── STEP 6: Reputation delta ───────────────────────────────
    result.rep_delta = compute_rep_delta(signal, result.outcome, result.net_pnl_bps, profile)

    return result


def settle_single_tp(signal, checkpoints, verified_ref, profile):
    twap_min = min(c.price for c in checkpoints)
    twap_max = max(c.price for c in checkpoints)
    twap_exit = checkpoints[-1].price

    stop_hit = twap_min <= signal.stop_price
    target_hit = twap_max >= signal.target_price

    if stop_hit:
        outcome = OUTCOME.LOSS
        exit_price = signal.stop_price
    elif target_hit:
        outcome = OUTCOME.WIN
        exit_price = signal.target_price
    else:
        outcome = OUTCOME.EXPIRED
        exit_price = twap_exit

    gross_pnl_bps = (exit_price - verified_ref) / verified_ref * 10000

    return SettlementResult(outcome=outcome, exit_price=exit_price, gross_pnl_bps=gross_pnl_bps)


def settle_multi_tp(signal, checkpoints, verified_ref):
    """
    Lógica multi-TP del Swing Agent:
    - 50% qty cierra en TP1 (R:R 2:1)
    - 50% qty cierra en TP2 (R:R 3:1, publicado como target_price)
    - BE @ +1.5% (mover stop a entry tras alcanzar trigger)

    Outcomes:
    - WIN si TWAP alcanza tp2 antes que stop
    - WIN_PARTIAL si TWAP alcanza tp1, luego stop (BE o original) sin llegar a tp2
    - LOSS si TWAP alcanza stop antes que tp1
    """
    tp1 = signal.metadata["tp1"]
    tp2 = signal.target_price
    stop = signal.stop_price
    be_trigger_pct = signal.metadata.get("be_trigger_pct", 1.5) / 100

    tp1_hit = False
    be_active = False
    current_stop = stop

    for cp in checkpoints:
        # BE trigger
        if not be_active and cp.price >= verified_ref * (1 + be_trigger_pct):
            be_active = True
            current_stop = verified_ref

        # TP1 hit
        if not tp1_hit and cp.price >= tp1:
            tp1_hit = True

        # TP2 (target final) hit
        if cp.price >= tp2:
            outcome = OUTCOME.WIN
            # 50% en TP1 + 50% en TP2
            if tp1_hit:
                gross_pnl_bps = compute_partial_pnl(verified_ref, tp1, tp2, 0.5, 0.5)
            else:
                # Edge case: salto directo a TP2 sin TP1
                gross_pnl_bps = (tp2 - verified_ref) / verified_ref * 10000
            return SettlementResult(outcome=outcome, exit_price=tp2, gross_pnl_bps=gross_pnl_bps)

        # Stop hit
        if cp.price <= current_stop:
            if tp1_hit:
                # WIN_PARTIAL: ganamos en 50% (TP1), perdemos/BE en 50% (stop o BE)
                outcome = OUTCOME.WIN_PARTIAL
                exit_partial = current_stop   # BE o stop original
                gross_pnl_bps = compute_partial_pnl(verified_ref, tp1, exit_partial, 0.5, 0.5)
            else:
                outcome = OUTCOME.LOSS
                exit_partial = current_stop
                gross_pnl_bps = (exit_partial - verified_ref) / verified_ref * 10000
            return SettlementResult(outcome=outcome, exit_price=exit_partial, gross_pnl_bps=gross_pnl_bps)

    # Horizon expirado
    twap_exit = checkpoints[-1].price
    if tp1_hit:
        outcome = OUTCOME.WIN_PARTIAL
        gross_pnl_bps = compute_partial_pnl(verified_ref, tp1, twap_exit, 0.5, 0.5)
    else:
        outcome = OUTCOME.EXPIRED
        gross_pnl_bps = (twap_exit - verified_ref) / verified_ref * 10000
    return SettlementResult(outcome=outcome, exit_price=twap_exit, gross_pnl_bps=gross_pnl_bps)


def compute_partial_pnl(entry, partial_exit, final_exit, qty1_frac, qty2_frac):
    """PnL ponderado para multi-TP."""
    pnl_partial_bps = (partial_exit - entry) / entry * 10000
    pnl_final_bps = (final_exit - entry) / entry * 10000
    return pnl_partial_bps * qty1_frac + pnl_final_bps * qty2_frac
```

---

## 6. Gas-Adjusted PnL

(Sin cambios respecto al original — gas accounting por perfil es igual.)

```python
def compute_gas_cost_bps(signal, eth_usd: float) -> float:
    swap_gas_used = signal.execution_receipt.gas_used
    swap_gas_price = signal.execution_receipt.gas_price
    swap_gas_eth = swap_gas_used * swap_gas_price / 1e18
    risk_gas_eth = 50_000 * swap_gas_price / 1e18
    total_gas_eth = swap_gas_eth + risk_gas_eth
    total_gas_usd = total_gas_eth * eth_usd
    bps = (total_gas_usd / signal.position_size_usd) * 10000
    return min(bps, 50.0)
```

---

## 7. Slippage Attribution

```python
def compute_signal_slippage_bps(signal) -> float:
    spot_at_pub = get_spot_at_block(signal.token, signal.published_at_block)
    twap_at_pub = signal.reference_price
    return abs(spot_at_pub - twap_at_pub) / twap_at_pub * 10000
```

Solo `signal_quality_slippage` entra en `net_pnl_bps`. La slippage de ejecución es del Trading Agent.

---

## 8. Reputation Math (con WIN_PARTIAL)

```python
def compute_rep_delta(signal, outcome, net_pnl_bps, profile) -> int:
    # Base delta por outcome
    if outcome == WIN:
        base = 100 + max(0, net_pnl_bps * 0.5)
    elif outcome == WIN_PARTIAL:
        base = 50 + max(0, net_pnl_bps * 0.3)   # menos que WIN, más que EXPIRED
    elif outcome == LOSS:
        base = -150 + min(0, net_pnl_bps * 0.5)
    elif outcome == EXPIRED:
        base = net_pnl_bps * 0.3
    elif outcome == INCONCLUSIVE:
        base = 0
    elif outcome == INVALID:
        base = -300

    # Calibración Brier
    brier = compute_historical_brier(signal.publisher, lookback=20)
    if brier is None:           cal_mult = 1.0
    elif brier <= 0.20:         cal_mult = 1.20
    elif brier <= 0.25:         cal_mult = 1.00
    else:                       cal_mult = 0.70

    # Significancia por perfil (scalper genera más, requiere más muestras)
    n_signals_7d = count_signals_7d(signal.publisher)
    threshold = 30 if profile == "scalper" else 10
    sig_weight = min(n_signals_7d / threshold, 1.0)

    rep_delta = int(base * cal_mult * sig_weight)
    return max(-300, min(300, rep_delta))
```

### Brier Score (incluye WIN_PARTIAL como 0.5)

```python
def compute_historical_brier(publisher: str, lookback: int = 20) -> float | None:
    signals = get_settled_signals(publisher, last=lookback)
    decisive = [s for s in signals if s.outcome in [WIN, WIN_PARTIAL, LOSS]]
    if len(decisive) < 5:
        return None

    sq_errors = []
    for s in decisive:
        # WIN = 1.0, WIN_PARTIAL = 0.5, LOSS = 0.0
        actual = 1.0 if s.outcome == WIN else (0.5 if s.outcome == WIN_PARTIAL else 0.0)
        predicted = s.confidence_bps / 10000
        sq_errors.append((predicted - actual) ** 2)

    return sum(sq_errors) / len(sq_errors)
```

---

## 9. Outputs

### 9.1 On-chain (Base Sepolia — ValidatorSettle)
```solidity
event SignalSettled(
    bytes32 indexed signalId,
    uint8 outcome,        // 0=WIN, 1=WIN_PARTIAL, 2=LOSS, 3=EXPIRED, 4=INCONCLUSIVE, 5=INVALID
    int256 pnlBps,
    uint256 timestamp
);
```

### 9.2 API local (FastAPI /status)
```json
{
  "signal_id": "0x...",
  "profile": "swing",
  "outcome": "WIN_PARTIAL",
  "exit_price": 3450.21,
  "tp1_hit": true,
  "tp2_hit": false,
  "be_activated": true,
  "gross_pnl_bps": 75.2,
  "gas_cost_bps": 2.3,
  "slippage_bps": 1.8,
  "net_pnl_bps": 71.1,
  "rep_delta": 75,
  "settled_at_block": 12349800
}
```

---

## 10. Reglas Estrictas — NUNCA Hacer

1. **NUNCA usar precio spot para evaluar stop/target** (siempre TWAP)
2. **NUNCA usar LLM en el camino crítico de settlement** (determinismo absoluto)
3. **NUNCA aprobar señal con `cardinality < 100`**
4. **NUNCA aprobar señal con `coverage < 80%` de checkpoints**
5. **NUNCA computar `rep_delta` que exceda ±300**
6. **NUNCA actualizar score más allá de [0, 10000]**
7. **NUNCA postear attestación sin re-verificar `reference_price`**
8. **NUNCA computar PnL contra `execution_price`**
9. **NUNCA aplicar gas del Validator al PnL**
10. **NUNCA modificar el algoritmo en runtime**
11. **NUNCA dejar señales pendientes >24h**
12. **NUNCA tratar WIN_PARTIAL como LOSS** (es positivo, ~50% del WIN máximo)
13. **NUNCA aplicar la misma ventana TWAP a swing y scalper** (1800s vs 600s)

---

## 11. Filosofía Final

Eres el árbitro neutral. **Para el Swing Agent, validas raramente pero con precisión multi-TP**. **Para el Scalper Agent, validas frecuentemente con ventanas TWAP cortas**. Tu prestigio se gana siendo predecible: si alguien duda de un veredicto, debe poder correr tu algoritmo localmente con los mismos inputs on-chain y obtener el mismo resultado.

`WIN_PARTIAL` es una innovación clave del sistema multi-TP del Swing Agent: refleja que el trader **realmente cerró 50% en ganancia (TP1)** aunque el resto haya retrocedido. Tratar eso como LOSS sería castigar al agente por cerrar parcial responsablemente.
