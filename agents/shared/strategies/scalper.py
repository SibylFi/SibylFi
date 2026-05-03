"""
Scalper strategy — adaptive 4-setup LONG entry on 1m/5m.

Implements the spec in agents/agent-research-scalper.md. Pure rule logic
over a pre-computed `ScalperFeatures` snapshot. The 4 setups (Wyckoff
Spring, EMA20 Pullback, RSI Bounce, 20-bar Breakout) are detected upstream
by indicator helpers; this module:

  1. Runs anti-DD / multi-asset / regime gates.
  2. Picks the highest-weight active setup (`adaptive_score`).
  3. Rejects if score < ml_min[mode].
  4. Builds R:R 2:1 single-TP levels with confluence bonus.
  5. Caps confidence at 8500 (stricter than swing).
"""
from __future__ import annotations

from agents.shared.strategies.snapshot import (
    ScalperFeatures,
    ScalperParams,
    StrategyResult,
)


def _select_setup(f: ScalperFeatures) -> tuple[str | None, float, int]:
    """Return (chosen_setup, adaptive_score, active_count).

    On ties the spec picks the setup whose pass evaluates last in this
    fixed order (Spring → Pullback → Bounce → Breakout); replicating
    Pine's `if … if greater than current` pattern.
    """
    chosen = None
    score = 0.0
    candidates = (
        ("Spring",   f.spring_signal),
        ("Pullback", f.pullback_signal),
        ("Bounce",   f.bounce_signal),
        ("Breakout", f.breakout_signal),
    )
    active = sum(1 for _, on in candidates if on)
    for name, on in candidates:
        if not on:
            continue
        w = f.setup_weights.get(name, 0.5)
        if chosen is None or w > score:
            chosen, score = name, w
    return chosen, score, active


def evaluate_scalper(
    f: ScalperFeatures,
    params: ScalperParams | None = None,
) -> StrategyResult:
    p = params or ScalperParams()

    # ── Anti-DD ──────────────────────────────────────────────────────────
    if f.consec_losses >= 3:
        return StrategyResult(False, f"dd_pause_consec_losses:{f.consec_losses}")
    if f.daily_pnl_pct <= p.daily_loss_limit_pct:
        return StrategyResult(False, f"daily_loss_breached:{f.daily_pnl_pct:.2f}")
    if f.in_cooldown:
        return StrategyResult(False, "cooldown_active")

    # ── Multi-asset filter ───────────────────────────────────────────────
    if f.btc_change_20b <= p.btc_crash_pct:
        return StrategyResult(False, f"btc_crash:{f.btc_change_20b:.2f}")
    if f.use_rel_strength and f.relative_strength <= 0:
        return StrategyResult(False, "weak_relative_strength")
    if f.bullish_consensus < 1:
        return StrategyResult(False, "no_bullish_consensus")

    # ── Regime / structure ───────────────────────────────────────────────
    if not f.has_structure:
        return StrategyResult(False, "no_market_structure")

    # ── Pick the strongest active setup ──────────────────────────────────
    chosen, score, active = _select_setup(f)
    if chosen is None:
        return StrategyResult(False, "no_setup_active")

    ml_min = p.ml_min_thresholds.get(p.mode, 0.50)
    if score < ml_min:
        return StrategyResult(
            False,
            f"adaptive_score_below_threshold:{score:.2f}<{ml_min:.2f}",
        )

    # ── TWAP integrity ───────────────────────────────────────────────────
    if f.twap_30m <= 0:
        return StrategyResult(False, "twap_unavailable")
    deviation = abs(f.spot_price - f.twap_30m) / f.twap_30m
    if deviation > p.twap_max_deviation:
        return StrategyResult(False, f"twap_deviation:{deviation:.4f}")

    # ── Levels (R:R 2:1 single TP) ───────────────────────────────────────
    entry = f.close
    stop = entry * (1.0 - p.sl_pct)
    risk = entry - stop
    target = entry + risk * p.tp_rr

    # ── Confidence base ──────────────────────────────────────────────────
    conf = p.confidence_per_setup.get(chosen, 6500)
    has_confluence = active >= 2
    if has_confluence:
        conf = int(conf * p.confluence_multiplier)

    if (
        f.historical_brier is not None
        and f.historical_brier > 0.25
        and f.real_win_rate is not None
    ):
        anchored = int(f.real_win_rate * 10000)
        conf = int(0.70 * anchored + 0.30 * conf)

    conf = max(0, min(p.confidence_cap, conf))

    # ── Horizon (shorten under high vol) ─────────────────────────────────
    horizon_seconds = p.horizon_1m if f.tf == "1m" else p.horizon_5m
    if f.atr_pct > p.high_vol_atr_pct:
        horizon_seconds = int(horizon_seconds * p.high_vol_horizon_mult)

    return StrategyResult(
        accept=True,
        reason="ok",
        setup=chosen,
        reference_price=f.twap_30m,
        target_price=round(target, 6),
        stop_price=round(stop, 6),
        horizon_seconds=horizon_seconds,
        confidence_bps_base=conf,
        confidence_bps_cap=p.confidence_cap,
        metadata={
            "setup": chosen,
            "adaptive_score": round(score, 4),
            "active_count": active,
            "confluence": has_confluence,
            "rr_structure": "2:1 single TP",
            "be_trigger_pct": 1.0,
            "trailing": True,
            "tf": f.tf,
            "btc_change_20b": f.btc_change_20b,
            "bullish_consensus": f"{f.bullish_consensus}/3",
            "mode": p.mode,
        },
    )
