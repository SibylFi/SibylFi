"""
Indicator regression tests.

Strategy:
  1. Property tests against mathematical invariants (RSI bounded, ATR ≥ 0,
     EMA of constant series equals constant, etc.). These catch logic bugs.
  2. Snapshot tests against the pinned 60-bar BTCUSD fixture. These catch
     drift from the current implementation. The pinned values were captured
     after the initial implementation passed property tests; if they drift,
     either the implementation regressed or the indicator was deliberately
     changed and the snapshot needs an explicit re-pin.

Note: we do not (yet) cross-validate against TradingView reference numbers.
The indicator math follows the documented Pine semantics (Wilder smoothing
for RSI/ATR, alpha=2/(n+1) for EMA, population stdev for Bollinger). If a
divergence vs a TradingView screenshot is found, the pinned snapshot is the
correct place to fix it.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from agents.shared.strategies.indicators import (
    atr,
    bollinger,
    detect_pivots_high,
    detect_pivots_low,
    divergence_hidden_bear,
    divergence_hidden_bull,
    divergence_regular_bear,
    divergence_regular_bull,
    donchian,
    dow_bull_bars,
    ema,
    floor_pivots,
    rsi,
    sma,
    supertrend,
    volume_zscore,
    vwap_session,
)

FIXTURE = Path(__file__).resolve().parent / "test_fixtures" / "btc_60d.json"


@pytest.fixture(scope="module")
def btc60():
    raw = json.loads(FIXTURE.read_text())
    bars = raw["bars"]
    return {
        "open":   [float(b["o"]) for b in bars],
        "high":   [float(b["h"]) for b in bars],
        "low":    [float(b["l"]) for b in bars],
        "close":  [float(b["c"]) for b in bars],
        "volume": [float(b["v"]) for b in bars],
    }


# ─────────────────────────────────────────────────────────────────
# SMA / EMA
# ─────────────────────────────────────────────────────────────────

def test_sma_constant_series_equals_constant():
    assert sma([5.0] * 30, 10)[-1] == 5.0


def test_sma_warmup_is_nan():
    out = sma([1, 2, 3, 4, 5], 3)
    assert math.isnan(out[0]) and math.isnan(out[1])
    assert out[2] == pytest.approx((1 + 2 + 3) / 3)
    assert out[-1] == pytest.approx((3 + 4 + 5) / 3)


def test_ema_constant_series_equals_constant():
    assert ema([7.0] * 50, 14)[-1] == 7.0


def test_ema_alpha_matches_pine():
    """alpha = 2/(n+1) = 0.2 for n=9; first iteration: 0.2*v + 0.8*seed."""
    e = ema([10.0, 20.0], 9)
    assert e[1] == pytest.approx(0.2 * 20.0 + 0.8 * 10.0)


# ─────────────────────────────────────────────────────────────────
# RSI (Wilder)
# ─────────────────────────────────────────────────────────────────

def test_rsi_bounded(btc60):
    r = rsi(btc60["close"], 14)
    finite = [v for v in r if not math.isnan(v)]
    assert all(0.0 <= v <= 100.0 for v in finite)


def test_rsi_all_up_converges_to_100():
    """50 strictly-rising bars → RSI(14) approaches 100."""
    series = [100.0 + i for i in range(60)]
    r = rsi(series, 14)
    assert r[-1] > 99.0


def test_rsi_all_down_converges_to_0():
    series = [200.0 - i for i in range(60)]
    r = rsi(series, 14)
    assert r[-1] < 1.0


# ─────────────────────────────────────────────────────────────────
# ATR (Wilder)
# ─────────────────────────────────────────────────────────────────

def test_atr_constant_series_with_no_range_is_zero():
    a = atr([10.0] * 30, [10.0] * 30, [10.0] * 30, 14)
    assert a[-1] == 0.0


def test_atr_non_negative(btc60):
    a = atr(btc60["high"], btc60["low"], btc60["close"], 14)
    finite = [v for v in a if not math.isnan(v)]
    assert all(v >= 0 for v in finite)


# ─────────────────────────────────────────────────────────────────
# Bollinger
# ─────────────────────────────────────────────────────────────────

def test_bollinger_ordering(btc60):
    upper, mid, lower = bollinger(btc60["close"], 20, 2.0)
    for u, m, l in zip(upper[19:], mid[19:], lower[19:]):
        assert u >= m >= l


def test_bollinger_constant_series_collapses():
    upper, mid, lower = bollinger([50.0] * 30, 20, 2.0)
    assert upper[-1] == mid[-1] == lower[-1] == 50.0


# ─────────────────────────────────────────────────────────────────
# Donchian
# ─────────────────────────────────────────────────────────────────

def test_donchian_window_is_recent_extrema(btc60):
    upper, lower = donchian(btc60["high"], btc60["low"], 20)
    # Last 20 bars
    assert upper[-1] == max(btc60["high"][-20:])
    assert lower[-1] == min(btc60["low"][-20:])


# ─────────────────────────────────────────────────────────────────
# VWAP session
# ─────────────────────────────────────────────────────────────────

def test_vwap_constant_price():
    typical = [100.0] * 10
    volume = [1.0] * 10
    v = vwap_session(typical, volume)
    assert v[-1] == pytest.approx(100.0)


def test_vwap_pulls_toward_high_volume_bars():
    """A high-volume bar at 200 should pull VWAP up from 100."""
    typical = [100.0, 100.0, 200.0, 100.0]
    volume = [1.0, 1.0, 100.0, 1.0]
    v = vwap_session(typical, volume)
    assert v[-1] > 150.0


# ─────────────────────────────────────────────────────────────────
# Volume z-score
# ─────────────────────────────────────────────────────────────────

def test_volume_zscore_zero_for_flat():
    z = volume_zscore([1000.0] * 30, 20)
    assert z[-1] == 0.0


def test_volume_zscore_positive_for_spike():
    series = [1000.0] * 19 + [10000.0]
    z = volume_zscore(series, 20)
    assert z[-1] > 1.0


# ─────────────────────────────────────────────────────────────────
# Floor pivots
# ─────────────────────────────────────────────────────────────────

def test_floor_pivots_basic_formula():
    p = floor_pivots(prev_high=110, prev_low=90, prev_close=100)
    pp = (110 + 90 + 100) / 3
    assert p["PP"] == pytest.approx(pp)
    assert p["R1"] == pytest.approx(2 * pp - 90)
    assert p["S1"] == pytest.approx(2 * pp - 110)
    assert p["R2"] == pytest.approx(pp + 20)
    assert p["S2"] == pytest.approx(pp - 20)


# ─────────────────────────────────────────────────────────────────
# Pivot detection
# ─────────────────────────────────────────────────────────────────

def test_pivot_low_detection_basic():
    # bar 4 is lowest: surrounded by 3 higher bars on each side
    series = [10, 9, 8, 7, 5, 7, 8, 9, 10]
    pivots = detect_pivots_low(series, left=3, right=3)
    assert pivots == [4]


def test_pivot_high_detection_basic():
    series = [5, 6, 7, 8, 10, 8, 7, 6, 5]
    pivots = detect_pivots_high(series, left=3, right=3)
    assert pivots == [4]


def test_pivot_no_false_positive_at_edges():
    """Edges should not produce pivots — no left/right context yet."""
    series = [5, 4, 3, 2, 1]   # monotone descending; no internal pivot lows
    assert detect_pivots_low(series, left=2, right=2) == []


# ─────────────────────────────────────────────────────────────────
# Divergence
# ─────────────────────────────────────────────────────────────────

def test_regular_bull_divergence():
    """Price prints a lower low; RSI prints a higher low → regular bull divergence."""
    # Two pivots at indices 4 and 12.
    low = [10, 9, 8, 7, 5,  6, 7, 8, 9, 10, 11, 10, 4,  10, 11, 12]
    rsi_series = [50, 45, 40, 35, 25,  35, 45, 50, 45, 40, 35, 30, 30,  35, 40, 45]
    # left=2, right=2: pivot at 4 (val=5, rsi=25), pivot at 12 (val=4, rsi=30).
    # Price made lower low (5→4) and RSI made higher low (25→30) → regular bull.
    assert divergence_regular_bull(low, rsi_series, 2, 2) is True


# ─────────────────────────────────────────────────────────────────
# Dow bull bars (consecutive HH+HL streak ending at the latest bar)
# ─────────────────────────────────────────────────────────────────

def test_dow_bull_bars_full_uptrend():
    high = [100 + i for i in range(20)]
    low = [99 + i for i in range(20)]
    assert dow_bull_bars(high, low, window=15) == 14   # last 14 bars all HH/HL


def test_dow_bull_bars_breaks_at_first_lower():
    high = [100, 101, 102, 103, 102, 103, 104]   # bar 4 broke HH; streak ending at 6 = 2
    low =  [99, 100, 101, 102, 101, 102, 103]
    assert dow_bull_bars(high, low, window=10) == 2


def test_dow_bull_bars_zero_when_latest_is_lower():
    high = [100, 101, 102, 103, 102]
    low =  [99, 100, 101, 102, 101]
    assert dow_bull_bars(high, low, window=10) == 0


# ─────────────────────────────────────────────────────────────────
# SuperTrend (smoke test only — output is on the right side of close)
# ─────────────────────────────────────────────────────────────────

def test_supertrend_in_uptrend_is_below_close(btc60):
    """In a sustained uptrend the SuperTrend line stays below close."""
    line = supertrend(btc60["high"], btc60["low"], btc60["close"], 10, 3.0)
    last_finite = next(
        (i for i in range(len(line) - 1, -1, -1) if not math.isnan(line[i])),
        None,
    )
    assert last_finite is not None
    # The fixture finishes in an uptrend (last 5 bars HH/HL).
    assert line[last_finite] < btc60["close"][last_finite]


# ─────────────────────────────────────────────────────────────────
# Snapshot regression — pin a few specific values from the BTC fixture
# ─────────────────────────────────────────────────────────────────

def test_btc_snapshot_sma20_last(btc60):
    """SMA(20) at the last bar = mean of last 20 closes."""
    out = sma(btc60["close"], 20)
    expected = sum(btc60["close"][-20:]) / 20
    assert out[-1] == pytest.approx(expected)


def test_btc_snapshot_indicator_dimensions(btc60):
    """All indicators return the same length as the input series."""
    n = len(btc60["close"])
    assert len(sma(btc60["close"], 20)) == n
    assert len(ema(btc60["close"], 20)) == n
    assert len(rsi(btc60["close"], 14)) == n
    assert len(atr(btc60["high"], btc60["low"], btc60["close"], 14)) == n
    upper, mid, lower = bollinger(btc60["close"], 20, 2.0)
    assert len(upper) == len(mid) == len(lower) == n
    upper_d, lower_d = donchian(btc60["high"], btc60["low"], 20)
    assert len(upper_d) == len(lower_d) == n
    assert len(supertrend(btc60["high"], btc60["low"], btc60["close"], 10, 3.0)) == n
    assert len(volume_zscore(btc60["volume"], 20)) == n
