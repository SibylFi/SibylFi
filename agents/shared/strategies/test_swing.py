"""
Swing strategy unit tests.

Each test starts from a "perfect" snapshot that satisfies all 5 confluences
and the TWAP integrity gate, then mutates one field to verify the
corresponding rejection branch fires. The happy-path test pins the
computed entry/stop/tp1/tp2 numerically against the spec formulas.
"""
from __future__ import annotations

import dataclasses

from agents.shared.strategies.snapshot import StrategyResult, SwingFeatures, SwingParams
from agents.shared.strategies.swing import evaluate_swing


def perfect() -> SwingFeatures:
    """Snapshot satisfying every swing gate."""
    return SwingFeatures(
        token="eip155:84532/erc20:0xWETH",
        tf="4h",
        spot_price=3450.0,
        twap_30m=3450.0,
        open_=3440.0,
        high=3460.0,
        low=3430.0,                 # wicks below ema10 then closes above
        close=3450.0,
        volume=1500.0,
        avg_volume_20=1200.0,
        ema10=3445.0,
        ema55=3400.0,
        ema100=3300.0,
        ema200=3000.0,
        rsi_14=58.0,
        atr_14=30.0,
        pivot_R3=3600.0,
        ema_stack_bull=True,
        price_above_ema200=True,
        dow_bull_bars=22,
        bull_div_regular=True,
        bull_div_hidden=False,
        bear_div_regular=False,
        bear_div_hidden=False,
        pullback_to_ema10=True,
        bull_candle=True,
        volume_ok=True,
    )


def with_(f: SwingFeatures, **kw) -> SwingFeatures:
    return dataclasses.replace(f, **kw)


# ─── Happy path ─────────────────────────────────────────────────────────


def test_happy_path_levels_and_metadata():
    r = evaluate_swing(perfect())
    assert r.accept and r.reason == "ok"
    assert r.setup == "strict_5_confluence"
    assert r.reference_price == 3450.0

    # entry=3450, sl=0.5%, risk=17.25
    assert r.stop_price == round(3450.0 * 0.995, 6)
    risk = 3450.0 - 3450.0 * 0.995
    expected_tp1 = 3450.0 + risk * 2.0
    expected_tp2 = 3450.0 + risk * 3.0
    assert r.metadata["tp1"] == round(expected_tp1, 6)
    assert r.target_price == round(expected_tp2, 6)

    # confidence: base 7500 + div_regular 500 + dow_long 0 (bars=22 < 30)
    assert r.confidence_bps_base == 8000
    assert r.confidence_bps_cap == 9000
    assert r.horizon_seconds == 86400          # 4h → 1 day


def test_horizon_per_tf():
    assert evaluate_swing(with_(perfect(), tf="4h")).horizon_seconds == 86400
    assert evaluate_swing(with_(perfect(), tf="8h")).horizon_seconds == 172800
    assert evaluate_swing(with_(perfect(), tf="1d")).horizon_seconds == 432000


def test_dow_long_bonus_applied_above_threshold():
    r = evaluate_swing(with_(perfect(), dow_bull_bars=35))
    # base 7500 + div_regular 500 + dow_long 500 = 8500
    assert r.confidence_bps_base == 8500


def test_confidence_cap_enforced():
    # Force every bonus to push above cap, verify cap binds
    p = SwingParams(confidence_base=9500, div_regular_bonus=500, dow_long_bonus=500)
    r = evaluate_swing(with_(perfect(), dow_bull_bars=40), p)
    assert r.confidence_bps_base == 9000


def test_pivot_r3_caps_target():
    # tp2 unbounded would be 3450 + 17.25 * 3 = 3501.75; pivot below that but
    # high enough that cap×0.99 still sits above entry.
    r = evaluate_swing(with_(perfect(), pivot_R3=3490.0))
    assert r.accept
    assert r.metadata["pivot_R3_capped"] is True
    assert r.target_price == round(3490.0 * 0.99, 6)


def test_pivot_r3_below_entry_rejected():
    """If R3 caps tp2 below entry, the strategy must abort instead of returning a loss."""
    r = evaluate_swing(with_(perfect(), pivot_R3=3460.0))
    assert not r.accept
    assert r.reason == "pivot_R3_below_entry"


# ─── Rejection branches (one per gate) ──────────────────────────────────


def _rej(features: SwingFeatures) -> StrategyResult:
    r = evaluate_swing(features)
    assert not r.accept, f"expected rejection, got {r}"
    return r


def test_reject_when_ema_stack_not_bull():
    assert _rej(with_(perfect(), ema_stack_bull=False)).reason == "ema_stack_not_bull"


def test_reject_when_price_below_ema200():
    assert _rej(with_(perfect(), price_above_ema200=False)).reason == "price_below_ema200"


def test_reject_when_dow_streak_too_short():
    r = _rej(with_(perfect(), dow_bull_bars=10))
    assert r.reason.startswith("dow_streak_too_short")


def test_reject_when_bear_warning():
    assert _rej(with_(perfect(), bear_warning=True)).reason == "bear_warning_active"


def test_reject_when_no_divergence():
    r = _rej(with_(perfect(), bull_div_regular=False, bull_div_hidden=False))
    assert r.reason == "no_bull_divergence"


def test_reject_when_pullback_incomplete():
    assert _rej(with_(perfect(), pullback_to_ema10=False)).reason == "pullback_setup_incomplete"
    assert _rej(with_(perfect(), bull_candle=False)).reason == "pullback_setup_incomplete"
    assert _rej(with_(perfect(), volume_ok=False)).reason == "pullback_setup_incomplete"


def test_reject_when_twap_deviation_exceeds_3pct():
    r = _rej(with_(perfect(), spot_price=3450.0 * 1.04))   # +4%
    assert r.reason.startswith("twap_deviation")


def test_reject_when_twap_unavailable():
    assert _rej(with_(perfect(), twap_30m=0.0)).reason == "twap_unavailable"


# ─── Brier-anchored confidence calibration ──────────────────────────────


def test_brier_anchoring_pulls_confidence_toward_real_win_rate():
    """If brier > 0.22, conf is anchored 70% to historical win rate."""
    f = with_(perfect(), historical_brier=0.30, real_win_rate=0.55)
    r = evaluate_swing(f)
    # base+div_bonus=8000; anchored = 0.7*5500 + 0.3*8000 = 3850 + 2400 = 6250
    assert r.confidence_bps_base == 6250


def test_brier_anchoring_skipped_when_brier_low():
    f = with_(perfect(), historical_brier=0.10, real_win_rate=0.55)
    r = evaluate_swing(f)
    assert r.confidence_bps_base == 8000   # untouched


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
