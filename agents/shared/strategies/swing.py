"""
Swing strategy — strict 5-confluence LONG entry on 4H/1D.

Implements the spec in agents/agent-research-swing.md. Pure rule logic over
a pre-computed `SwingFeatures` snapshot. The strategy is deterministic;
the LLM only post-calibrates `confidence_bps` and writes the thesis.

Required confluences (all must hold; rejection on any miss):
  1. EMA stack bullish (ema10 > ema55 > ema100 > ema200)
  2. Price above EMA200 (Murphy primary trend)
  3. Dow HH+HL streak ≥ params.min_dow_bars (factor tiempo)
  4. No active bear-warning
  5. Bullish RSI divergence (regular OR hidden)
  6. Pullback to EMA10 + bull candle + volume confirming

Plus integrity gate: |spot − twap_30m| / twap_30m ≤ params.twap_max_deviation.

Output levels (Elder R:R 2:1 / 3:1 multi-TP):
  entry = close
  stop  = entry × (1 − sl_pct)
  tp1   = entry + (entry − stop) × tp1_rr   (50% close trigger; metadata)
  tp2   = entry + (entry − stop) × tp2_rr   (final target)
  if tp2 > pivot_R3 → tp2 = pivot_R3 × 0.99 (Murphy cap)

Horizon: 1d→432000 (5 days), 8h→172800, 4h→86400.
"""
from __future__ import annotations

from agents.shared.strategies.snapshot import (
    StrategyResult,
    SwingFeatures,
    SwingParams,
)


def _horizon_for_tf(tf: str) -> int:
    return {"4h": 86400, "8h": 172800, "1d": 432000}.get(tf, 86400)


def evaluate_swing(
    f: SwingFeatures,
    params: SwingParams | None = None,
) -> StrategyResult:
    p = params or SwingParams()

    # ── Confluence gates (in spec order) ─────────────────────────────────
    if not f.ema_stack_bull:
        return StrategyResult(False, "ema_stack_not_bull")

    if not f.price_above_ema200:
        return StrategyResult(False, "price_below_ema200")

    if f.dow_bull_bars < p.min_dow_bars:
        return StrategyResult(False, f"dow_streak_too_short:{f.dow_bull_bars}<{p.min_dow_bars}")

    if f.bear_warning:
        return StrategyResult(False, "bear_warning_active")

    div_bull = f.bull_div_regular or f.bull_div_hidden
    if not div_bull:
        return StrategyResult(False, "no_bull_divergence")

    if not (f.pullback_to_ema10 and f.bull_candle and f.volume_ok):
        return StrategyResult(False, "pullback_setup_incomplete")

    # ── TWAP integrity (manipulation guard) ──────────────────────────────
    if f.twap_30m <= 0:
        return StrategyResult(False, "twap_unavailable")
    deviation = abs(f.spot_price - f.twap_30m) / f.twap_30m
    if deviation > p.twap_max_deviation:
        return StrategyResult(False, f"twap_deviation:{deviation:.4f}")

    # ── Levels (Elder R:R 2:1 / 3:1) ─────────────────────────────────────
    entry = f.close
    stop = entry * (1.0 - p.sl_pct)
    risk = entry - stop                  # = entry * sl_pct
    tp1 = entry + risk * p.tp1_rr
    tp2 = entry + risk * p.tp2_rr

    capped = False
    if f.pivot_R3 > 0 and tp2 > f.pivot_R3:
        tp2 = f.pivot_R3 * 0.99
        capped = True
        # Recompute effective realized R:R for transparency
        if tp2 <= entry:
            return StrategyResult(False, "pivot_R3_below_entry")

    # ── Confidence base (LLM may anchor via Brier; never exceed cap) ─────
    conf = p.confidence_base
    if f.bull_div_regular:
        conf += p.div_regular_bonus
    if f.dow_bull_bars >= p.dow_long_threshold:
        conf += p.dow_long_bonus

    # Brier-anchored calibration (deterministic; LLM-style anchor without LLM)
    if (
        f.historical_brier is not None
        and f.historical_brier > 0.22
        and f.real_win_rate is not None
    ):
        anchored = int(f.real_win_rate * 10000)
        conf = int(0.70 * anchored + 0.30 * conf)

    conf = max(0, min(p.confidence_cap, conf))

    horizon_seconds = _horizon_for_tf(f.tf)

    return StrategyResult(
        accept=True,
        reason="ok",
        setup="strict_5_confluence",
        reference_price=f.twap_30m,
        target_price=round(tp2, 6),
        stop_price=round(stop, 6),
        horizon_seconds=horizon_seconds,
        confidence_bps_base=conf,
        confidence_bps_cap=p.confidence_cap,
        metadata={
            "tp1": round(tp1, 6),
            "be_trigger_pct": 1.5,
            "rr_structure": "2:1 / 3:1 multi-TP",
            "tf": f.tf,
            "dow_bull_bars": f.dow_bull_bars,
            "div_kind": "regular" if f.bull_div_regular else "hidden",
            "pivot_R3_capped": capped,
        },
    )
