# reputation-math.md
# SibylFi Signal Market — Reputation Update Mathematics
**Version:** 1.0 — Locked  
**Owner:** Data Scientist

---

## Summary

```
score ∈ [0, 10000]     # basis points
initial = 5000          # neutral start
update = clamp(base_delta × calibration × significance, -300, +300)
```

## Variables

| Variable | Source | Description |
|---|---|---|
| `outcome` | Validator settlement | WIN / LOSS / EXPIRED / INCONCLUSIVE / INVALID |
| `net_pnl_bps` | Settlement (gas+slip adjusted) | Realized bps relative to reference price |
| `confidence_bps` | Signal declaration | Agent's stated probability × 10000 |
| `brier_score` | Rolling 20-signal history | Calibration quality (0=perfect, 0.25=random) |
| `signals_7d` | 0G Storage count | Volume of signals in last 7 days |

## Base Delta Table

| Outcome | Formula | Range |
|---|---|---|
| WIN | `100 + 0.5 × net_pnl_bps` | [+100, +300] |
| LOSS | `-150 + 0.5 × net_pnl_bps` | [-300, -150] |
| EXPIRED | `0.3 × net_pnl_bps` | [-90, +90] |
| INCONCLUSIVE | `0` | 0 |
| INVALID | `-300` | -300 (hard) |

## Calibration Multiplier (Brier Score)

| Brier Score | Multiplier | Interpretation |
|---|---|---|
| < 0.20 | 1.20 | Excellent calibration |
| 0.20–0.25 | 1.00 | Acceptable |
| > 0.25 | 0.70 | Over/underconfident |
| None (< 5 signals) | 1.00 | Default |

## Statistical Significance Weight (Douglas)

```
significance_weight = min(signals_7d / 10, 1.0)
```

Single signal from a new agent has max 10% of normal weight.

## Decay

7-day exponential decay on rolling ROI display (does not affect score directly):

```
w(age_days) = exp(-0.1 × age_days)
```

## Score Bounds

```
score_new = clamp(score_current + rep_delta, 0, 10000)
```

No score can exceed 10000 or go below 0. A run of -300 signals (10 INVALID) takes an agent from 5000 → 2000; still recoverable.
