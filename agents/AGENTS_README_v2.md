# SibylFi Agents — Doc Structure (v2.0)

## Estructura final de Research Agents

El sistema soporta **2 perfiles de Research Agents** validados con backtests reales en TradingView:

| Perfil | Doc | Pine origen | TF | WR target | Frecuencia |
|---|---|---|---|---|---|
| **Swing** | `agent-research-swing.md` | Cartagena LONG PRO Trend Hunter | 4H–1D | 60-80% | 5-15/mes |
| **Scalper** | `agent-research-scalper.md` | Cartagena SibylFi LONG Adaptive v4 | 1m–5m | 50-55% | 80-150/mes |

## Archivos a actualizar en GitHub

### En `/agents/` (raíz)

| Archivo | Acción | Notas |
|---|---|---|
| `agent-research-swing.md` | **NUEVO** ✓ | Reemplaza meanrev (semánticamente diferente, mejor base teórica) |
| `agent-research-scalper.md` | **NUEVO** ✓ | Reemplaza momentum (mismo perfil, mejor implementación) |
| `agent-research-meanrev.md` | **ELIMINAR** | Reemplazado por swing |
| `agent-research-momentum.md` | **ELIMINAR** | Reemplazado por scalper |
| `agent-research-news.md` | **ELIMINAR** | No hay Pine que lo respalde |
| `agent-risk.md` | **ACTUALIZAR** | Soporta perfil swing+scalper |
| `agent-validator.md` | **ACTUALIZAR** | Soporta WIN_PARTIAL + multi-TP |
| `agent-trading.md` | **ACTUALIZAR** | Portfolio dual swing+scalper |

### En `/specs/` (si existe esta carpeta)

| Archivo | Acción |
|---|---|
| `signal-validator.md` | **ACTUALIZAR a v2.0** (TWAP por perfil + WIN_PARTIAL) |
| `reputation-math.md` | **ACTUALIZAR a v2.0** (significance threshold por perfil) |

## Cambios clave v1 → v2

### Schema de señales

**v1 (legacy):**
```json
{
  "target_price": 3502.00,
  "stop_price": 3432.96,
  "horizon_seconds": 86400,
  "confidence_bps": 8500
}
```

**v2 — Scalper (single TP):**
```json
{
  "target_price": 3484.92,
  "stop_price": 3432.96,
  "horizon_seconds": 1800,
  "metadata": { "setup": "Pullback", "tf": "5m" }
}
```

**v2 — Swing (multi-TP):**
```json
{
  "target_price": 3502.00,
  "stop_price": 3432.96,
  "horizon_seconds": 86400,
  "metadata": {
    "tp1": 3484.92,
    "be_trigger_pct": 1.5,
    "rr_structure": "2:1 / 3:1 multi-TP"
  }
}
```

### Outcome Enum (Validator)

| Outcome | v1 | v2 |
|---|---|---|
| WIN | ✓ | ✓ |
| **WIN_PARTIAL** | — | **NUEVO** (TP1 hit + stop después) |
| LOSS | ✓ | ✓ |
| EXPIRED | ✓ | ✓ |
| INCONCLUSIVE | ✓ | ✓ |
| INVALID | ✓ | ✓ |

### TWAP Windows (Validator)

| | v1 | v2 Swing | v2 Scalper |
|---|---|---|---|
| reference_price window | 1800s | 1800s | **600s** |
| settlement window | 1800s | 1800s | **600s** |
| checkpoint interval | 60s | 60s | **15s** |
| spot/twap deviation max | 3% | 3% | **1.5%** |

### Reputation (Math)

| | v1 | v2 |
|---|---|---|
| Outcomes en cálculo | 5 | **6 (incluye WIN_PARTIAL)** |
| Significance threshold | 10 fijo | **10 swing / 30 scalper** |
| Brier WIN_PARTIAL value | — | **0.5 (intermedio)** |

### Risk Agent — Thresholds por perfil

| Threshold | Swing | Scalper |
|---|---|---|
| Stop max | 1.0% | 1.0% |
| R:R mínimo | 2.5 | 2.0 |
| Slippage max | 1.5% | **0.8%** |
| Spot/TWAP deviation max | 3.0% | **1.5%** |

### Trading Agent — Portfolio Dual

| | Swing | Scalper |
|---|---|---|
| Capital allocation | 60% | 40% |
| Max positions abiertas | 3 | 5 |
| Max position size | $60 | $25 |
| Loop check interval | 5 min | 30 sec |
| Cycle budget máx | 0.5% capital | 0.1% capital |

## Commit messages sugeridos

```bash
# Commit 1: Reemplazar Research Agents legacy
git rm agents/agent-research-meanrev.md
git rm agents/agent-research-momentum.md
git rm agents/agent-research-news.md
git add agents/agent-research-swing.md
git add agents/agent-research-scalper.md
git commit -m "docs(agents): replace legacy research agents with validated swing+scalper profiles

- agent-research-swing.md based on Cartagena LONG PRO Trend Hunter Pine (4H-1D)
- agent-research-scalper.md based on Cartagena SibylFi Adaptive v4 Pine (1m-5m)
- Both backtested in TradingView with real metrics
- Long-only design aligned with Uniswap Trading API constraints"

# Commit 2: Actualizar agentes infraestructura
git add agents/agent-risk.md
git add agents/agent-validator.md
git add agents/agent-trading.md
git commit -m "docs(agents): update Risk/Validator/Trading agents to v2 with profile-aware logic

- Risk Agent: thresholds differentiated by profile (swing/scalper)
- Validator Agent: WIN_PARTIAL outcome for multi-TP swing signals
- Trading Agent: dual portfolio allocation (60% swing / 40% scalper)
- Validator TWAP windows scaled by profile (1800s swing / 600s scalper)"

# Commit 3: Specs
git add specs/signal-validator.md
git add specs/reputation-math.md
git commit -m "docs(specs): update validator + reputation math to v2.0 with profile support

- TWAP windows by profile
- WIN_PARTIAL outcome with weighted Brier (actual=0.5)
- Significance threshold differentiated (10 swing / 30 scalper)
- Multi-TP settlement logic with BE detection"
```
