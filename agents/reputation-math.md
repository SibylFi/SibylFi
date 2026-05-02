# reputation-math.md
# SibylFi Signal Market — Reputation Update Mathematics
**Version:** 2.0 — Soporta WIN_PARTIAL + thresholds por perfil

---

## Summary

```
score ∈ [0, 10000]
initial = 5000
update = clamp(base_delta × calibration × significance, -300, +300)
```

## Variables

| Variable | Source |
|---|---|
| `outcome` | Validator: WIN / WIN_PARTIAL / LOSS / EXPIRED / INCONCLUSIVE / INVALID |
| `net_pnl_bps` | Settlement (gas+slip adjusted) |
| `confidence_bps` | Signal declaration |
| `brier_score` | Rolling 20-signal history |
| `signals_7d` | 0G Storage |
| `profile` | swing / scalper / intraday |

## Base Delta Table (incluye WIN_PARTIAL)

| Outcome | Formula | Range |
|---|---|---|
| WIN | `100 + 0.5 × net_pnl_bps` | [+100, +300] |
| **WIN_PARTIAL** | `50 + 0.3 × net_pnl_bps` | [+50, +200] |
| LOSS | `-150 + 0.5 × net_pnl_bps` | [-300, -150] |
| EXPIRED | `0.3 × net_pnl_bps` | [-90, +90] |
| INCONCLUSIVE | `0` | 0 |
| INVALID | `-300` | -300 |

## Calibration Multiplier (Brier Score)

| Brier Score | Multiplier | Interpretación |
|---|---|---|
| < 0.20 | 1.20 | Excelente |
| 0.20–0.25 | 1.00 | Aceptable |
| > 0.25 | 0.70 | Sobrestima |
| None (<5 señales) | 1.00 | Default |

## Significance Weight (Douglas) — diferenciado por perfil

```python
threshold = 30 if profile == "scalper" else 10
significance_weight = min(signals_7d / threshold, 1.0)
```

**Por qué la diferencia:**
- **Scalper** genera 80-150 trades/mes — necesita 30 mínimos para significancia (3 días de data)
- **Swing** genera 5-15 trades/mes — 10 ya es muestra significativa

## Brier Score (con WIN_PARTIAL = 0.5)

```python
def compute_brier(signals: List[Signal]) -> float | None:
    decisive = [s for s in signals if s.outcome in [WIN, WIN_PARTIAL, LOSS]]
    if len(decisive) < 5:
        return None
    sq_errors = []
    for s in decisive:
        actual = 1.0 if s.outcome == WIN else (0.5 if s.outcome == WIN_PARTIAL else 0.0)
        predicted = s.confidence_bps / 10000
        sq_errors.append((predicted - actual) ** 2)
    return sum(sq_errors) / len(sq_errors)
```

WIN_PARTIAL como 0.5 refleja que el agente acertó "a medias" — TP1 sí, TP2 no. Esto da calibración más justa que tratar WIN_PARTIAL como WIN o LOSS binario.

## Decay (display rolling, no afecta score)

```
w(age_days) = exp(-0.1 × age_days)
```

7 días de ventana exponencial.

## Score Bounds

```
score_new = clamp(score_current + rep_delta, 0, 10000)
```

## Ejemplos por Perfil

### Swing — Trade ganador con multi-TP completo
```
outcome: WIN
net_pnl_bps: +250 (R:R 3:1)
base = 100 + 0.5 × 250 = 225
brier: 0.18 → cal_mult: 1.20
signals_7d: 8 (de 10 threshold) → sig_weight: 0.80
rep_delta = 225 × 1.20 × 0.80 = +216 bps
```

### Swing — TP1 hit pero stop después
```
outcome: WIN_PARTIAL
net_pnl_bps: +75 (50% en TP1 a +1%, 50% en BE)
base = 50 + 0.3 × 75 = 72
cal_mult: 1.20, sig_weight: 0.80
rep_delta = 72 × 1.20 × 0.80 = +69 bps
```

### Scalper — Trade perdedor
```
outcome: LOSS
net_pnl_bps: -55 (stop hit)
base = -150 + 0.5 × (-55) = -177
brier: 0.23 → cal_mult: 1.00
signals_7d: 25 (de 30 threshold) → sig_weight: 0.83
rep_delta = -177 × 1.00 × 0.83 = -147 bps
```

## Anti-Gaming Defenses

| Attack | Defense |
|---|---|
| Spam near-zero signals | `significance_weight` requiere 10 (swing) o 30 (scalper) signals |
| Self-purchase wash | `x402` enforcement: caller ≠ publisher |
| Cherry-pick | `rep_delta` × `log(1 + buyers_count)` if available |
| Confidence inflation | Brier `calibration_multiplier` penaliza overconfidence |
| Profile mismatch | Validator rechaza si `profile` declarado ≠ inferido por horizon |

---

*Locked v2.0 — soporta WIN_PARTIAL + thresholds diferenciados por perfil*
