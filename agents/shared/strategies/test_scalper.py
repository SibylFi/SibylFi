"""
Scalper strategy unit tests.

Same structure as test_swing: a `perfect()` snapshot + per-gate mutations.
"""
from __future__ import annotations

import dataclasses

from agents.shared.strategies.scalper import evaluate_scalper
from agents.shared.strategies.snapshot import (
    ScalperFeatures,
    ScalperParams,
    StrategyResult,
)


def perfect() -> ScalperFeatures:
    return ScalperFeatures(
        token="eip155:84532/erc20:0xWETH",
        tf="5m",
        spot_price=3450.0,
        twap_30m=3450.0,
        close=3450.0,
        atr_pct=0.5,
        spring_signal=False,
        pullback_signal=True,        # only pullback active by default
        bounce_signal=False,
        breakout_signal=False,
        has_structure=True,
        is_ranging=False,
        is_bullish=True,
        btc_change_20b=0.5,
        bullish_consensus=3,
        relative_strength=0.4,
        use_rel_strength=False,
        setup_weights={"Spring": 0.5, "Pullback": 0.7, "Bounce": 0.5, "Breakout": 0.5},
        consec_losses=0,
        daily_pnl_pct=0.5,
        in_cooldown=False,
    )


def with_(f: ScalperFeatures, **kw) -> ScalperFeatures:
    return dataclasses.replace(f, **kw)


# ─── Happy path ─────────────────────────────────────────────────────────


def test_happy_path_pullback_setup():
    r = evaluate_scalper(perfect())
    assert r.accept and r.reason == "ok"
    assert r.setup == "Pullback"
    assert r.reference_price == 3450.0

    # entry=3450, sl=0.5%, risk=17.25; tp = entry + risk*2
    assert r.stop_price == round(3450.0 * 0.995, 6)
    expected_target = 3450.0 + (3450.0 - 3450.0 * 0.995) * 2.0
    assert r.target_price == round(expected_target, 6)

    # Pullback base = 7000, no confluence (only one active), no Brier override
    assert r.confidence_bps_base == 7000
    assert r.confidence_bps_cap == 8500
    assert r.horizon_seconds == 3600           # 5m default
    assert r.metadata["confluence"] is False
    assert r.metadata["active_count"] == 1


def test_horizon_short_for_1m():
    r = evaluate_scalper(with_(perfect(), tf="1m"))
    assert r.horizon_seconds == 1800


def test_horizon_shrinks_under_high_vol():
    # atr_pct=1.0 > 0.8 threshold, default mult 0.7
    r = evaluate_scalper(with_(perfect(), atr_pct=1.0))
    assert r.horizon_seconds == int(3600 * 0.7)


def test_confluence_bonus_applied_when_two_setups_fire():
    """Two setups firing → 1.10× confidence bonus."""
    f = with_(
        perfect(),
        spring_signal=True,
        pullback_signal=True,
    )
    r = evaluate_scalper(f)
    # Pullback weight (0.7) > Spring (0.5), so chosen=Pullback (base 7000)
    # active=2 → confluence multiplier 1.10 → 7700
    assert r.metadata["active_count"] == 2
    assert r.metadata["confluence"] is True
    assert r.confidence_bps_base == 7700


def test_select_highest_weight_setup():
    """If multiple setups fire, the one with the highest adaptive weight wins."""
    f = with_(
        perfect(),
        spring_signal=True,
        pullback_signal=True,
        breakout_signal=True,
        setup_weights={
            "Spring": 0.55,
            "Pullback": 0.55,
            "Bounce": 0.5,
            "Breakout": 0.95,        # clearly the strongest
        },
    )
    r = evaluate_scalper(f)
    assert r.setup == "Breakout"


def test_confidence_cap_enforced():
    # Brier override pushes huge anchored win rate; cap should clamp
    f = with_(perfect(), historical_brier=0.30, real_win_rate=0.99)
    r = evaluate_scalper(f)
    assert r.confidence_bps_base == 8500   # cap


# ─── Rejection branches ─────────────────────────────────────────────────


def _rej(f: ScalperFeatures, params: ScalperParams | None = None) -> StrategyResult:
    r = evaluate_scalper(f, params)
    assert not r.accept, f"expected rejection, got {r}"
    return r


def test_reject_on_consec_losses():
    assert _rej(with_(perfect(), consec_losses=3)).reason.startswith("dd_pause_consec_losses")


def test_reject_on_daily_loss_breached():
    assert _rej(with_(perfect(), daily_pnl_pct=-3.5)).reason.startswith("daily_loss_breached")


def test_reject_on_cooldown():
    assert _rej(with_(perfect(), in_cooldown=True)).reason == "cooldown_active"


def test_reject_on_btc_crash():
    assert _rej(with_(perfect(), btc_change_20b=-2.5)).reason.startswith("btc_crash")


def test_reject_on_weak_relative_strength_when_enabled():
    f = with_(perfect(), use_rel_strength=True, relative_strength=-0.1)
    assert _rej(f).reason == "weak_relative_strength"


def test_relative_strength_ignored_when_disabled():
    """Even with negative relative_strength, scalper should accept if use_rel_strength=False."""
    f = with_(perfect(), use_rel_strength=False, relative_strength=-0.1)
    assert evaluate_scalper(f).accept


def test_reject_on_no_consensus():
    assert _rej(with_(perfect(), bullish_consensus=0)).reason == "no_bullish_consensus"


def test_reject_on_no_structure():
    assert _rej(with_(perfect(), has_structure=False)).reason == "no_market_structure"


def test_reject_when_no_setup_active():
    f = with_(
        perfect(),
        spring_signal=False, pullback_signal=False,
        bounce_signal=False, breakout_signal=False,
    )
    assert _rej(f).reason == "no_setup_active"


def test_reject_below_ml_threshold_in_balanced_mode():
    """Pullback weight 0.45 < 0.50 (Balanced) → rejected."""
    f = with_(
        perfect(),
        setup_weights={"Spring": 0.45, "Pullback": 0.45, "Bounce": 0.45, "Breakout": 0.45},
    )
    assert _rej(f).reason.startswith("adaptive_score_below_threshold")


def test_discovery_mode_more_permissive():
    """Same low weights, but Discovery mode (0.40 threshold) accepts."""
    f = with_(
        perfect(),
        setup_weights={"Spring": 0.45, "Pullback": 0.45, "Bounce": 0.45, "Breakout": 0.45},
    )
    p = ScalperParams(mode="Discovery")
    assert evaluate_scalper(f, p).accept


def test_conservative_mode_stricter():
    """Pullback weight 0.55 < 0.60 (Conservative) → rejected."""
    f = with_(
        perfect(),
        setup_weights={"Spring": 0.5, "Pullback": 0.55, "Bounce": 0.5, "Breakout": 0.5},
    )
    p = ScalperParams(mode="Conservative")
    assert _rej(f, p).reason.startswith("adaptive_score_below_threshold")


def test_reject_on_twap_deviation_exceeds_1_5_pct():
    """Scalper TWAP guard is stricter than swing — 1.5% threshold."""
    r = _rej(with_(perfect(), spot_price=3450.0 * 1.02))   # +2% > 1.5%
    assert r.reason.startswith("twap_deviation")


def test_swing_threshold_not_used_for_scalper():
    """A 2% deviation that swing tolerates must still reject scalper."""
    # 2% < 3% (swing) but > 1.5% (scalper)
    r = evaluate_scalper(with_(perfect(), spot_price=3450.0 * 1.02))
    assert not r.accept
    assert r.reason.startswith("twap_deviation")


def test_reject_when_twap_unavailable():
    assert _rej(with_(perfect(), twap_30m=0.0)).reason == "twap_unavailable"


# ─── Metadata correctness ──────────────────────────────────────────────


def test_metadata_carries_setup_and_consensus():
    r = evaluate_scalper(perfect())
    assert r.metadata["setup"] == "Pullback"
    assert r.metadata["bullish_consensus"] == "3/3"
    assert r.metadata["mode"] == "Balanced"
    assert r.metadata["rr_structure"] == "2:1 single TP"
    assert r.metadata["trailing"] is True


if __name__ == "__main__":
    import sys
    fail = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ✓ {name}")
            except AssertionError as e:
                print(f"  ✗ {name}: {e}")
                fail += 1
    sys.exit(1 if fail else 0)
