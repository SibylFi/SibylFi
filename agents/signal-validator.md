# signal-validator.md
# SibylFi Signal Market — Validator Algorithm Specification
**Version:** 2.0 — LOCKED  
**Owner:** Data Scientist  
**Cambios v2:** TWAP windows por perfil, outcome WIN_PARTIAL para multi-TP, soporte swing+scalper

---

## 1. Detección de Perfil

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

## 2. TWAP Window por Perfil

| Propósito | Swing | Scalper |
|---|---|---|
| `reference_price` | 1800s | **600s** |
| Settlement TWAP | 1800s | 600s |
| Intervalo checkpoints | 60s | **15s** |
| Spot/TWAP deviation max | 3% | **1.5%** |

Justificación: el scalper necesita ventana proporcional a su TF (10 min para señales de 1h). El swing absorbe wicks en 30 min.

---

## 3. Outcomes (incluye WIN_PARTIAL)

| Outcome | Condición |
|---|---|
| `WIN` | TWAP alcanza target final antes que stop |
| `WIN_PARTIAL` | Multi-TP: TP1 hit, luego stop (BE u original) |
| `LOSS` | TWAP alcanza stop antes que cualquier TP |
| `EXPIRED` | Horizon termina sin alcanzar nada |
| `INCONCLUSIVE` | <80% checkpoints o cardinality<100 |
| `INVALID` | Reference price mismatch >0.1% |

---

## 4. Validator Algorithm

```python
def settle_signal(signal: Signal) -> SettlementResult:
    profile = detect_profile(signal)
    pool = get_pool(signal.token)

    # 1. Oracle pre-check
    if pool.slot0().observationCardinality < 100:
        return SettlementResult(outcome=INCONCLUSIVE, rep_delta=0)

    # 2. Verify reference_price (con ventana del perfil)
    twap_window = 600 if profile == "scalper" else 1800
    verified_ref = get_twap(pool, twap_window, at_block=signal.published_at_block)
    if abs(verified_ref - signal.reference_price) / verified_ref > 0.001:
        return SettlementResult(outcome=INVALID, rep_delta=-300)

    # 3. Collect checkpoints
    interval = 15 if profile == "scalper" else 60
    horizon_blocks = signal.horizon_seconds // 2
    checkpoints = collect_twap_checkpoints(
        pool, signal.published_at_block,
        signal.published_at_block + horizon_blocks,
        interval_seconds=interval
    )
    coverage = len(checkpoints) / (signal.horizon_seconds // interval)
    if coverage < 0.80:
        return SettlementResult(outcome=INCONCLUSIVE, rep_delta=0)

    # 4. Outcome (single o multi TP)
    has_multi_tp = signal.metadata.get("tp1") is not None and profile == "swing"
    if has_multi_tp:
        result = settle_multi_tp(signal, checkpoints, verified_ref)
    else:
        result = settle_single_tp(signal, checkpoints, verified_ref, profile)

    # 5. Gas-adjusted PnL
    eth_usd = chainlink_eth_usd()
    result.gas_cost_bps = min(compute_gas_cost_bps(signal, eth_usd), 50)
    result.slippage_bps = compute_signal_slippage_bps(signal)
    result.net_pnl_bps = result.gross_pnl_bps - result.gas_cost_bps - result.slippage_bps

    # 6. Reputation delta
    result.rep_delta = compute_rep_delta(signal, result.outcome, result.net_pnl_bps, profile)
    return result


def settle_single_tp(signal, checkpoints, verified_ref, profile):
    twap_min = min(c.price for c in checkpoints)
    twap_max = max(c.price for c in checkpoints)

    stop_hit = twap_min <= signal.stop_price
    target_hit = twap_max >= signal.target_price

    if stop_hit:
        outcome, exit_price = OUTCOME.LOSS, signal.stop_price
    elif target_hit:
        outcome, exit_price = OUTCOME.WIN, signal.target_price
    else:
        outcome, exit_price = OUTCOME.EXPIRED, checkpoints[-1].price

    gross_pnl_bps = (exit_price - verified_ref) / verified_ref * 10000
    return SettlementResult(outcome=outcome, exit_price=exit_price, gross_pnl_bps=gross_pnl_bps)


def settle_multi_tp(signal, checkpoints, verified_ref):
    """Swing Agent multi-TP con BE."""
    tp1 = signal.metadata["tp1"]
    tp2 = signal.target_price
    stop = signal.stop_price
    be_trigger = signal.metadata.get("be_trigger_pct", 1.5) / 100

    tp1_hit = False
    be_active = False
    current_stop = stop

    for cp in checkpoints:
        # BE trigger
        if not be_active and cp.price >= verified_ref * (1 + be_trigger):
            be_active = True
            current_stop = verified_ref

        # TP1 hit
        if not tp1_hit and cp.price >= tp1:
            tp1_hit = True

        # TP2 hit (target final)
        if cp.price >= tp2:
            outcome = OUTCOME.WIN
            if tp1_hit:
                gross_pnl_bps = compute_partial_pnl(verified_ref, tp1, tp2, 0.5, 0.5)
            else:
                gross_pnl_bps = (tp2 - verified_ref) / verified_ref * 10000
            return SettlementResult(outcome=outcome, exit_price=tp2, gross_pnl_bps=gross_pnl_bps)

        # Stop hit
        if cp.price <= current_stop:
            if tp1_hit:
                outcome = OUTCOME.WIN_PARTIAL
                gross_pnl_bps = compute_partial_pnl(verified_ref, tp1, current_stop, 0.5, 0.5)
            else:
                outcome = OUTCOME.LOSS
                gross_pnl_bps = (current_stop - verified_ref) / verified_ref * 10000
            return SettlementResult(outcome=outcome, exit_price=current_stop, gross_pnl_bps=gross_pnl_bps)

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
    pnl_partial_bps = (partial_exit - entry) / entry * 10000
    pnl_final_bps = (final_exit - entry) / entry * 10000
    return pnl_partial_bps * qty1_frac + pnl_final_bps * qty2_frac
```

---

## 5. Gas-Adjusted PnL

```python
gas_cost_bps = (gas_cost_usd / position_size_usd) * 10000
gas_cost_bps = min(gas_cost_bps, 50)
```

| Item | Cuenta? |
|---|---|
| Trading Agent swap | Sí |
| Risk Agent verification | Sí |
| Validator settlement | No |
| Research Agent publish | No |

---

## 6. Slippage Attribution

Solo `signal_quality_slippage` afecta a la reputación:

```python
signal_quality_slippage = abs(spot_at_publish - twap_at_publish) / twap × 10000
```

---

## 7. Reputation Math

```python
def compute_rep_delta(signal, outcome, net_pnl_bps, profile) -> int:
    if outcome == WIN:
        base = 100 + max(0, net_pnl_bps * 0.5)
    elif outcome == WIN_PARTIAL:
        base = 50 + max(0, net_pnl_bps * 0.3)
    elif outcome == LOSS:
        base = -150 + min(0, net_pnl_bps * 0.5)
    elif outcome == EXPIRED:
        base = net_pnl_bps * 0.3
    elif outcome == INCONCLUSIVE:
        base = 0
    elif outcome == INVALID:
        base = -300

    # Brier calibration
    brier = compute_historical_brier(signal.publisher)
    cal_mult = 1.20 if (brier and brier <= 0.20) else 0.70 if (brier and brier > 0.25) else 1.0

    # Significancia por perfil
    threshold = 30 if profile == "scalper" else 10
    sig_weight = min(count_signals_7d(signal.publisher) / threshold, 1.0)

    return max(-300, min(300, int(base * cal_mult * sig_weight)))
```

---

## 8. Schemas

### Scalper (single TP)
```json
{
  "publisher": "research-scalper.signalmarket.eth",
  "horizon_seconds": 1800,
  "metadata": {"setup": "Pullback", "tf": "5m"}
}
```

### Swing (multi-TP)
```json
{
  "publisher": "research-swing.signalmarket.eth",
  "horizon_seconds": 86400,
  "target_price": 3502.00,
  "metadata": {
    "tp1": 3484.92,
    "be_trigger_pct": 1.5,
    "rr_structure": "2:1 / 3:1 multi-TP"
  }
}
```

---

## 9. Backtest Validation

| Modelo | TF | WR | PF | DD |
|---|---|---|---|---|
| Cartagena LONG PRO (Swing) | 4H | 60-80% | 2.0-3.5 | <4% |
| Cartagena Adaptive v4 (Scalper) | 5m | 50-55% | 1.3-1.7 | <6% |

---

*Locked: Data Scientist — SibylFi Signal Market — v2.0*
