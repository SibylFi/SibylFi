"""
Strategy I/O types.

A *snapshot* is what `evaluate_swing` / `evaluate_scalper` receive: the
already-computed features at the latest bar (EMAs, RSI, divergence flags,
pivots, multi-asset state, adaptive weights, risk-state). The strategy
module is then a *pure* rule engine that maps snapshot → result.

This split exists so:
  1. Strategies are deterministic and unit-testable without OHLCV fixtures.
  2. The Research Agent (BaseResearchAgent in Task 2.3) computes features
     once per bar and may reuse them across calls.
  3. The LLM never participates in the direction or pass/fail decision —
     only post-hoc calibrates confidence_bps and writes the thesis.
"""
from __future__ import annotations

from dataclasses import dataclass, field


# ─── Snapshots ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SwingFeatures:
    """Pre-computed features for the swing strategy at the latest closed bar."""
    token: str
    tf: str                    # "4h" | "8h" | "1d"

    spot_price: float
    twap_30m: float

    open_: float
    high: float
    low: float
    close: float
    volume: float
    avg_volume_20: float

    ema10: float
    ema55: float
    ema100: float
    ema200: float
    rsi_14: float
    atr_14: float

    pivot_R3: float            # Murphy: target cap

    ema_stack_bull: bool       # ema10 > ema55 > ema100 > ema200
    price_above_ema200: bool

    dow_bull_bars: int         # consecutive HH+HL streak ending at this bar

    bull_div_regular: bool
    bull_div_hidden: bool
    bear_div_regular: bool
    bear_div_hidden: bool

    pullback_to_ema10: bool    # low ≤ ema10 ≤ close
    bull_candle: bool          # close > open and close > (high+low)/2
    volume_ok: bool            # volume > avg_volume_20 * params.min_volume_multiple

    bear_warning: bool = False
    historical_brier: float | None = None
    real_win_rate: float | None = None


@dataclass(frozen=True)
class ScalperFeatures:
    """Pre-computed features for the scalper strategy at the latest closed bar."""
    token: str
    tf: str                    # "1m" | "3m" | "5m"

    spot_price: float
    twap_30m: float

    close: float
    atr_pct: float             # ATR as % of close

    spring_signal: bool
    pullback_signal: bool
    bounce_signal: bool
    breakout_signal: bool

    has_structure: bool = True
    is_ranging: bool = False
    is_bullish: bool = True

    btc_change_20b: float = 0.0
    bullish_consensus: int = 3
    relative_strength: float = 0.0
    use_rel_strength: bool = False

    setup_weights: dict[str, float] = field(default_factory=lambda: {
        "Spring": 0.5, "Pullback": 0.5, "Bounce": 0.5, "Breakout": 0.5,
    })

    consec_losses: int = 0
    daily_pnl_pct: float = 0.0
    in_cooldown: bool = False

    historical_brier: float | None = None
    real_win_rate: float | None = None


# ─── Params (per-strategy tunables, exposed to multi-tenant config) ───────


@dataclass(frozen=True)
class SwingParams:
    min_dow_bars: int = 15
    min_volume_multiple: float = 1.0
    twap_max_deviation: float = 0.03   # Pine: 3% — manipulation guard
    sl_pct: float = 0.005              # 0.5% from entry
    tp1_rr: float = 2.0
    tp2_rr: float = 3.0
    confidence_base: int = 7500
    div_regular_bonus: int = 500
    dow_long_threshold: int = 30
    dow_long_bonus: int = 500
    confidence_cap: int = 9000


@dataclass(frozen=True)
class ScalperParams:
    twap_max_deviation: float = 0.015  # Pine: 1.5% — stricter than swing
    sl_pct: float = 0.005
    tp_rr: float = 2.0
    confidence_per_setup: dict[str, int] = field(default_factory=lambda: {
        "Spring": 6500,
        "Pullback": 7000,
        "Bounce": 6000,
        "Breakout": 7000,
    })
    confidence_cap: int = 8500
    confluence_multiplier: float = 1.10
    ml_min_thresholds: dict[str, float] = field(default_factory=lambda: {
        "Discovery":   0.40,
        "Balanced":    0.50,
        "Conservative": 0.60,
    })
    mode: str = "Balanced"
    btc_crash_pct: float = -2.0        # Pine: BTC drop in 20 bars that pauses LONGs
    daily_loss_limit_pct: float = -3.0
    horizon_1m: int = 1800             # 30 min
    horizon_5m: int = 3600             # 1 hour
    high_vol_atr_pct: float = 0.8      # ATR% above which horizon shrinks
    high_vol_horizon_mult: float = 0.7


# ─── Result ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class StrategyResult:
    """Output of a strategy module.

    `accept=False` carries `reason` explaining which gate rejected the bar.
    `accept=True` carries the full signal blueprint (entry, target, stop,
    horizon, base confidence, metadata) — the LLM may then nudge confidence
    via Brier-anchored calibration but cannot flip direction.
    """
    accept: bool
    reason: str

    setup: str | None = None
    reference_price: float | None = None
    target_price: float | None = None
    stop_price: float | None = None
    horizon_seconds: int | None = None
    confidence_bps_base: int | None = None
    confidence_bps_cap: int | None = None
    metadata: dict | None = None
