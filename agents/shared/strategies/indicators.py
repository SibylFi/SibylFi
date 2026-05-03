"""
Indicator math ported from the Pine scripts in /agents/*.pine.

All functions are pure (no I/O, no globals, no random). Inputs are plain
lists of floats; outputs are lists of floats or ints. Values that aren't yet
defined (e.g. the first `period - 1` bars of an SMA) are filled with float
NaN, so callers should slice off the warm-up.

Smoothing conventions:
  - SMA: simple arithmetic mean over the window.
  - EMA: TradingView ta.ema — alpha = 2/(period+1), seed = first close.
  - Wilder RMA: alpha = 1/period, seed = SMA(period). Used by RSI and ATR
    to match Pine's ta.rsi / ta.atr semantics.
  - Bollinger stdev: population (ddof=0), per Pine ta.stdev default.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

NaN = float("nan")


# ─────────────────────────────────────────────────────────────────────
# Moving averages
# ─────────────────────────────────────────────────────────────────────

def sma(series: list[float], period: int) -> list[float]:
    """Simple moving average. Output[i] for i < period-1 is NaN."""
    if period <= 0:
        raise ValueError("period must be > 0")
    out: list[float] = []
    rolling_sum = 0.0
    for i, v in enumerate(series):
        rolling_sum += v
        if i >= period:
            rolling_sum -= series[i - period]
        if i >= period - 1:
            out.append(rolling_sum / period)
        else:
            out.append(NaN)
    return out


def ema(series: list[float], period: int) -> list[float]:
    """Exponential MA, Pine ta.ema flavor: alpha = 2/(period+1), seed = first value."""
    if period <= 0:
        raise ValueError("period must be > 0")
    if not series:
        return []
    alpha = 2.0 / (period + 1.0)
    out = [series[0]]
    for v in series[1:]:
        out.append(alpha * v + (1 - alpha) * out[-1])
    return out


def _rma(series: list[float], period: int) -> list[float]:
    """
    Wilder's smoothing (Running Moving Average). alpha = 1/period.
    Seed = SMA(series[:period]). Output[i] for i < period-1 is NaN.
    """
    if period <= 0:
        raise ValueError("period must be > 0")
    n = len(series)
    out: list[float] = [NaN] * n
    if n < period:
        return out
    seed = sum(series[:period]) / period
    out[period - 1] = seed
    alpha = 1.0 / period
    for i in range(period, n):
        out[i] = alpha * series[i] + (1 - alpha) * out[i - 1]
    return out


# ─────────────────────────────────────────────────────────────────────
# Oscillators
# ─────────────────────────────────────────────────────────────────────

def rsi(close: list[float], period: int = 14) -> list[float]:
    """RSI(period) using Wilder smoothing. Matches Pine ta.rsi."""
    n = len(close)
    if n < 2:
        return [NaN] * n
    gains: list[float] = [0.0] + [max(close[i] - close[i - 1], 0.0) for i in range(1, n)]
    losses: list[float] = [0.0] + [max(close[i - 1] - close[i], 0.0) for i in range(1, n)]
    avg_gain = _rma(gains, period)
    avg_loss = _rma(losses, period)
    out: list[float] = []
    for g, l in zip(avg_gain, avg_loss):
        if math.isnan(g) or math.isnan(l):
            out.append(NaN)
        elif l == 0:
            out.append(100.0 if g > 0 else 50.0)
        else:
            rs = g / l
            out.append(100.0 - 100.0 / (1.0 + rs))
    return out


def atr(high: list[float], low: list[float], close: list[float], period: int = 14) -> list[float]:
    """ATR(period) using Wilder smoothing on True Range. Matches Pine ta.atr."""
    n = len(close)
    if not (n == len(high) == len(low)):
        raise ValueError("high/low/close must be equal length")
    tr: list[float] = [high[0] - low[0]]
    for i in range(1, n):
        tr.append(max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1]),
        ))
    return _rma(tr, period)


# ─────────────────────────────────────────────────────────────────────
# Bands and ranges
# ─────────────────────────────────────────────────────────────────────

def _stdev_pop(window: list[float]) -> float:
    n = len(window)
    if n == 0:
        return NaN
    m = sum(window) / n
    return math.sqrt(sum((x - m) ** 2 for x in window) / n)


def bollinger(
    close: list[float],
    period: int = 20,
    stddev: float = 2.0,
) -> tuple[list[float], list[float], list[float]]:
    """Returns (upper, middle, lower). Population stdev to match Pine ta.stdev."""
    mid = sma(close, period)
    upper: list[float] = []
    lower: list[float] = []
    for i, m in enumerate(mid):
        if math.isnan(m):
            upper.append(NaN)
            lower.append(NaN)
            continue
        window = close[max(0, i - period + 1): i + 1]
        sd = _stdev_pop(window)
        upper.append(m + stddev * sd)
        lower.append(m - stddev * sd)
    return upper, mid, lower


def supertrend(
    high: list[float],
    low: list[float],
    close: list[float],
    period: int = 10,
    multiplier: float = 3.0,
) -> list[float]:
    """
    SuperTrend line. Returns the active trend value per bar.
    Direction is encoded by which side of close the line lies on:
      line < close → uptrend (line is the trailing-stop floor)
      line > close → downtrend (line is the trailing-stop ceiling)
    """
    n = len(close)
    if not (n == len(high) == len(low)):
        raise ValueError("high/low/close must be equal length")
    a = atr(high, low, close, period)
    out: list[float] = [NaN] * n
    direction = 1   # 1=up, -1=down
    prev_final_upper = NaN
    prev_final_lower = NaN

    for i in range(n):
        if math.isnan(a[i]):
            continue
        hl2 = (high[i] + low[i]) / 2.0
        upper_basic = hl2 + multiplier * a[i]
        lower_basic = hl2 - multiplier * a[i]

        if math.isnan(prev_final_upper) or upper_basic < prev_final_upper or close[i - 1] > prev_final_upper:
            final_upper = upper_basic
        else:
            final_upper = prev_final_upper
        if math.isnan(prev_final_lower) or lower_basic > prev_final_lower or close[i - 1] < prev_final_lower:
            final_lower = lower_basic
        else:
            final_lower = prev_final_lower

        if math.isnan(out[i - 1]) if i > 0 else True:
            direction = 1
        elif out[i - 1] == prev_final_upper and close[i] > final_upper:
            direction = 1
        elif out[i - 1] == prev_final_lower and close[i] < final_lower:
            direction = -1

        out[i] = final_lower if direction == 1 else final_upper
        prev_final_upper = final_upper
        prev_final_lower = final_lower
    return out


def donchian(
    high: list[float],
    low: list[float],
    period: int = 20,
) -> tuple[list[float], list[float]]:
    """Returns (upper, lower) — highest(high, period) and lowest(low, period)."""
    n = len(high)
    upper: list[float] = []
    lower: list[float] = []
    for i in range(n):
        if i < period - 1:
            upper.append(NaN)
            lower.append(NaN)
        else:
            upper.append(max(high[i - period + 1: i + 1]))
            lower.append(min(low[i - period + 1: i + 1]))
    return upper, lower


# ─────────────────────────────────────────────────────────────────────
# Volume / VWAP
# ─────────────────────────────────────────────────────────────────────

def vwap_session(typical: list[float], volume: list[float]) -> list[float]:
    """
    Session VWAP. Treats the entire input series as one session — for crypto's
    24h-day, callers should slice per UTC day before calling.
    """
    n = len(typical)
    if n != len(volume):
        raise ValueError("typical/volume must be equal length")
    out: list[float] = []
    pv_sum = 0.0
    v_sum = 0.0
    for t, v in zip(typical, volume):
        pv_sum += t * v
        v_sum += v
        out.append(pv_sum / v_sum if v_sum > 0 else t)
    return out


def volume_zscore(volume: list[float], window: int = 20) -> list[float]:
    """Rolling volume z-score over the trailing `window` bars."""
    n = len(volume)
    out: list[float] = []
    for i in range(n):
        if i < window - 1:
            out.append(NaN)
            continue
        w = volume[i - window + 1: i + 1]
        m = sum(w) / window
        sd = _stdev_pop(w)
        out.append((volume[i] - m) / sd if sd > 0 else 0.0)
    return out


# ─────────────────────────────────────────────────────────────────────
# Floor pivots (classic)
# ─────────────────────────────────────────────────────────────────────

def floor_pivots(prev_high: float, prev_low: float, prev_close: float) -> dict:
    """Classic floor pivots from yesterday's OHLC. Returns PP, R1-3, S1-3."""
    pp = (prev_high + prev_low + prev_close) / 3.0
    diff = prev_high - prev_low
    return {
        "PP": pp,
        "R1": 2 * pp - prev_low,
        "S1": 2 * pp - prev_high,
        "R2": pp + diff,
        "S2": pp - diff,
        "R3": prev_high + 2 * (pp - prev_low),
        "S3": prev_low - 2 * (prev_high - pp),
    }


# ─────────────────────────────────────────────────────────────────────
# Pivot detection (TradingView ta.pivothigh / ta.pivotlow semantics)
# ─────────────────────────────────────────────────────────────────────

def detect_pivots_low(low: list[float], left: int, right: int) -> list[int]:
    """
    Indices where low[i] is strictly less than the `left` lows before AND the
    `right` lows after. A pivot at i is only confirmed once i + right bars
    have arrived.
    """
    n = len(low)
    pivots: list[int] = []
    for i in range(left, n - right):
        center = low[i]
        if any(low[j] <= center for j in range(i - left, i)):
            continue
        if any(low[j] <= center for j in range(i + 1, i + right + 1)):
            continue
        pivots.append(i)
    return pivots


def detect_pivots_high(high: list[float], left: int, right: int) -> list[int]:
    """Mirror of detect_pivots_low for highs."""
    n = len(high)
    pivots: list[int] = []
    for i in range(left, n - right):
        center = high[i]
        if any(high[j] >= center for j in range(i - left, i)):
            continue
        if any(high[j] >= center for j in range(i + 1, i + right + 1)):
            continue
        pivots.append(i)
    return pivots


# ─────────────────────────────────────────────────────────────────────
# Divergence detection
#
# Compares the two most recent confirmed pivots:
#   regular bull: price LL, RSI HL  (potential reversal up)
#   hidden bull:  price HL, RSI LL  (continuation up)
#   regular bear: price HH, RSI LH  (potential reversal down)
#   hidden bear:  price LH, RSI HH  (continuation down)
# ─────────────────────────────────────────────────────────────────────

def _last_two_pivots(pivots: list[int]) -> tuple[int, int] | None:
    if len(pivots) < 2:
        return None
    return pivots[-2], pivots[-1]


def divergence_regular_bull(low: list[float], rsi_series: list[float], left: int, right: int) -> bool:
    pair = _last_two_pivots(detect_pivots_low(low, left, right))
    if pair is None:
        return False
    a, b = pair
    return low[b] < low[a] and rsi_series[b] > rsi_series[a]


def divergence_hidden_bull(low: list[float], rsi_series: list[float], left: int, right: int) -> bool:
    pair = _last_two_pivots(detect_pivots_low(low, left, right))
    if pair is None:
        return False
    a, b = pair
    return low[b] > low[a] and rsi_series[b] < rsi_series[a]


def divergence_regular_bear(high: list[float], rsi_series: list[float], left: int, right: int) -> bool:
    pair = _last_two_pivots(detect_pivots_high(high, left, right))
    if pair is None:
        return False
    a, b = pair
    return high[b] > high[a] and rsi_series[b] < rsi_series[a]


def divergence_hidden_bear(high: list[float], rsi_series: list[float], left: int, right: int) -> bool:
    pair = _last_two_pivots(detect_pivots_high(high, left, right))
    if pair is None:
        return False
    a, b = pair
    return high[b] < high[a] and rsi_series[b] > rsi_series[a]


# ─────────────────────────────────────────────────────────────────────
# Dow theory — consecutive HH/HL streak ending at the current bar
# ─────────────────────────────────────────────────────────────────────

def dow_bull_bars(high: list[float], low: list[float], window: int) -> int:
    """
    Returns the count of consecutive bars (looking back at most `window` bars
    from the end) where each bar's high > prev high AND low > prev low.
    The streak must be unbroken — first non-HH-HL bar terminates the count.
    """
    if not (len(high) == len(low)):
        raise ValueError("high/low must be equal length")
    n = len(high)
    streak = 0
    for back in range(1, min(window, n)):
        i = n - back
        prev = i - 1
        if prev < 0:
            break
        if high[i] > high[prev] and low[i] > low[prev]:
            streak += 1
        else:
            break
    return streak
