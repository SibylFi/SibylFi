"""
Real OHLCV feature provider.

Fetches OHLCV from the Kraken public REST API (no key needed, no geo-block)
and runs indicators.py to produce SwingFeatures or ScalperFeatures at the
current bar.

Called by feature_provider.load_features when MOCK_MODE=0.  Raises on any
network or parsing failure so the caller can fall back to mock and log
degraded mode rather than surfacing a 500.
"""
from __future__ import annotations

import math
from typing import Literal

import httpx
import structlog

from agents.shared.strategies.indicators import (
    atr,
    bollinger,
    divergence_hidden_bear,
    divergence_hidden_bull,
    divergence_regular_bear,
    divergence_regular_bull,
    donchian,
    dow_bull_bars as _dow_bull_bars,
    ema,
    floor_pivots,
    rsi,
)
from agents.shared.strategies.snapshot import ScalperFeatures, SwingFeatures

log = structlog.get_logger(__name__)

_KRAKEN_BASE = "https://api.kraken.com/0/public"

# (query-pair, result-key)
_KRAKEN_PAIR: dict[str, tuple[str, str]] = {
    "WETH/USDC": ("ETHUSD",  "XETHZUSD"),
    "WBTC/USDC": ("XBTUSD",  "XXBTZUSD"),
    "ETH/USDC":  ("ETHUSD",  "XETHZUSD"),
    "BTC/USDC":  ("XBTUSD",  "XXBTZUSD"),
    "ARB/USDC":  ("ARBUSD",  "ARBUSD"),
    "OP/USDC":   ("OPUSD",   "OPUSD"),
}

# Fallback for CAIP-19 / ERC-20 token identifiers
_ADDR_PAIR: dict[str, tuple[str, str]] = {
    # WETH on Base Sepolia
    "0x4200000000000000000000000000000000000006": ("ETHUSD", "XETHZUSD"),
}

Profile = Literal["swing", "scalper"]


def kraken_pair(token: str) -> tuple[str, str]:
    """Map a SibylFi token identifier to a (query_pair, result_key) tuple."""
    if token in _KRAKEN_PAIR:
        return _KRAKEN_PAIR[token]
    token_lower = token.lower()
    for addr, pair in _ADDR_PAIR.items():
        if addr in token_lower:
            return pair
    if "btc" in token_lower or "wbtc" in token_lower:
        return ("XBTUSD", "XXBTZUSD")
    return ("ETHUSD", "XETHZUSD")


def fetch_kraken_ohlc(pair: str, interval_min: int) -> list[list]:
    """
    Fetch OHLC bars from Kraken public API.
    interval_min: 1 | 5 | 15 | 30 | 60 | 240 | 1440
    Returns up to 720 bars as [[time, o, h, l, c, vwap, vol, count], ...].
    Raises on any network or API error.
    """
    url = f"{_KRAKEN_BASE}/OHLC"
    params = {"pair": pair, "interval": interval_min}
    with httpx.Client(timeout=12.0) as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()
    body = resp.json()
    if body.get("error"):
        raise RuntimeError(f"Kraken API error: {body['error']}")
    result = body["result"]
    # The result dict has one key for the data and one "last" key
    data_key = next(k for k in result if k != "last")
    return result[data_key]


def parse_kraken_ohlcv(bars: list[list]) -> tuple[list[float], list[float], list[float], list[float], list[float]]:
    """Unpack Kraken OHLC rows into (opens, highs, lows, closes, volumes)."""
    opens  = [float(b[1]) for b in bars]
    highs  = [float(b[2]) for b in bars]
    lows   = [float(b[3]) for b in bars]
    closes = [float(b[4]) for b in bars]
    vols   = [float(b[6]) for b in bars]
    return opens, highs, lows, closes, vols


def load_features_real(profile: Profile, token: str) -> SwingFeatures | ScalperFeatures:
    """Compute live features from Kraken OHLCV.  Raises on any failure."""
    pair, result_key = kraken_pair(token)
    log.info("feature_provider_real.fetching", profile=profile, pair=pair, token=token)

    if profile == "swing":
        return _swing_features(pair, token)
    if profile == "scalper":
        return _scalper_features(pair, token)
    raise ValueError(f"unknown profile: {profile}")


# ─────────────────────────────────────────────────────────────────────────
# Swing (daily bars, 720 candles ≥ 200-bar EMA warmup)
# ─────────────────────────────────────────────────────────────────────────

def _swing_features(pair: str, token: str) -> SwingFeatures:
    bars = fetch_kraken_ohlc(pair, interval_min=1440)
    if len(bars) < 200:
        raise RuntimeError(f"too few daily bars from Kraken: {len(bars)}")

    opens, highs, lows, closes, vols = parse_kraken_ohlcv(bars)

    ema10_s  = ema(closes, 10)
    ema55_s  = ema(closes, 55)
    ema100_s = ema(closes, 100)
    ema200_s = ema(closes, 200)
    rsi14_s  = rsi(closes, 14)
    atr14_s  = atr(highs, lows, closes, 14)

    close_now = closes[-1]
    open_now  = opens[-1]
    high_now  = highs[-1]
    low_now   = lows[-1]
    vol_now   = vols[-1]
    avg_vol_20 = sum(vols[-21:-1]) / 20.0

    ema10_now  = ema10_s[-1]
    ema55_now  = ema55_s[-1]
    ema100_now = ema100_s[-1]
    ema200_now = ema200_s[-1]
    rsi_now    = rsi14_s[-1]
    atr_now    = atr14_s[-1]

    pivot_r3 = floor_pivots(highs[-2], lows[-2], closes[-2])["R3"]

    ema_stack_bull     = ema10_now > ema55_now > ema100_now > ema200_now
    price_above_ema200 = close_now > ema200_now
    dow_bars           = _dow_bull_bars(highs, lows, window=50)

    _l, _r = 5, 5
    div_reg_bull = divergence_regular_bull(lows, rsi14_s, _l, _r)
    div_hid_bull = divergence_hidden_bull(lows, rsi14_s, _l, _r)
    div_reg_bear = divergence_regular_bear(highs, rsi14_s, _l, _r)
    div_hid_bear = divergence_hidden_bear(highs, rsi14_s, _l, _r)

    pullback_to_ema10 = low_now <= ema10_now <= close_now
    bull_candle       = close_now > open_now and close_now > (high_now + low_now) / 2.0
    volume_ok         = vol_now > avg_vol_20 * 1.0

    # Kraken daily bars: close ≈ both spot and TWAP proxy
    spot_price = close_now
    twap_30m   = close_now

    log.info(
        "swing_features_computed",
        pair=pair,
        close=round(close_now, 2),
        ema_stack_bull=ema_stack_bull,
        price_above_ema200=price_above_ema200,
        dow_bull_bars=dow_bars,
        div_bull=div_reg_bull or div_hid_bull,
        pullback_setup=pullback_to_ema10 and bull_candle and volume_ok,
    )

    return SwingFeatures(
        token=token,
        tf="1d",
        spot_price=spot_price,
        twap_30m=twap_30m,
        open_=open_now,
        high=high_now,
        low=low_now,
        close=close_now,
        volume=vol_now,
        avg_volume_20=avg_vol_20,
        ema10=ema10_now,
        ema55=ema55_now,
        ema100=ema100_now,
        ema200=ema200_now,
        rsi_14=rsi_now,
        atr_14=atr_now,
        pivot_R3=pivot_r3,
        ema_stack_bull=ema_stack_bull,
        price_above_ema200=price_above_ema200,
        dow_bull_bars=dow_bars,
        bull_div_regular=div_reg_bull,
        bull_div_hidden=div_hid_bull,
        bear_div_regular=div_reg_bear,
        bear_div_hidden=div_hid_bear,
        pullback_to_ema10=pullback_to_ema10,
        bull_candle=bull_candle,
        volume_ok=volume_ok,
        bear_warning=False,
    )


# ─────────────────────────────────────────────────────────────────────────
# Scalper (5-minute bars, up to 720 candles)
# ─────────────────────────────────────────────────────────────────────────

def _scalper_features(pair: str, token: str) -> ScalperFeatures:
    bars = fetch_kraken_ohlc(pair, interval_min=5)
    if len(bars) < 25:
        raise RuntimeError(f"too few 5m bars from Kraken: {len(bars)}")

    opens, highs, lows, closes, vols = parse_kraken_ohlcv(bars)
    close_now = closes[-1]

    atr14_s = atr(highs, lows, closes, 14)
    atr_pct = atr14_s[-1] / close_now * 100.0 if close_now > 0 else 0.0

    ema20_s = ema(closes, 20)
    rsi14_s = rsi(closes, 14)
    _, _, bb_lower = bollinger(closes, 20, 2.0)
    dc_upper, _ = donchian(highs, lows, 20)

    # Spring: wick below 20-bar low with close above (Wyckoff test-and-reject)
    recent_low = min(lows[-21:-1])
    spring_signal = lows[-1] < recent_low and closes[-1] > recent_low

    # Pullback: was above EMA20, touched it, now back above
    pullback_signal = (
        len(ema20_s) >= 3
        and closes[-3] > ema20_s[-3]
        and lows[-2] <= ema20_s[-2]
        and closes[-1] >= ema20_s[-1]
    )

    # Bounce: RSI crossed 30 from below (oversold reversal)
    rsi_prev, rsi_cur = rsi14_s[-2], rsi14_s[-1]
    bounce_signal = (
        not (math.isnan(rsi_prev) or math.isnan(rsi_cur))
        and rsi_prev < 30.0
        and rsi_cur >= 30.0
    )

    # Breakout: current close above previous Donchian upper band
    breakout_signal = (
        len(dc_upper) >= 2
        and not math.isnan(dc_upper[-2])
        and closes[-1] > dc_upper[-2]
    )

    is_bullish    = closes[-1] > ema20_s[-1]
    is_ranging    = atr_pct < 0.3
    has_structure = not is_ranging or is_bullish

    c1 = closes[-1] > ema20_s[-1]
    c2 = len(ema20_s) >= 11 and ema20_s[-1] > ema20_s[-11]
    c3 = not math.isnan(rsi14_s[-1]) and rsi14_s[-1] > 50.0
    bullish_consensus = int(c1) + int(c2) + int(c3)

    # BTC correlation via a second Kraken call (skip for BTC itself)
    if pair in ("XBTUSD", "XXBTZUSD"):
        btc_change_20b    = (closes[-1] - closes[-21]) / closes[-21] * 100.0 if len(closes) >= 21 else 0.0
        relative_strength = 0.0
        use_rel_strength  = False
    else:
        try:
            btc_bars = fetch_kraken_ohlc("XBTUSD", interval_min=5)
            _, _, _, btc_closes, _ = parse_kraken_ohlcv(btc_bars)
            btc_change_20b    = (btc_closes[-1] - btc_closes[-21]) / btc_closes[-21] * 100.0
            tok_change_20b    = (closes[-1] - closes[-21]) / closes[-21] * 100.0 if len(closes) >= 21 else 0.0
            relative_strength = tok_change_20b - btc_change_20b
            use_rel_strength  = True
        except Exception as exc:
            log.warning("btc_fetch_failed", error=str(exc))
            btc_change_20b    = 0.0
            relative_strength = 0.0
            use_rel_strength  = False

    twap_30m = sum(closes[-6:]) / min(6, len(closes))

    setup_weights = {
        "Spring":   0.60 if spring_signal   else 0.50,
        "Pullback": 0.70 if pullback_signal  else 0.50,
        "Bounce":   0.65 if bounce_signal    else 0.50,
        "Breakout": 0.65 if breakout_signal  else 0.50,
    }

    log.info(
        "scalper_features_computed",
        pair=pair,
        close=round(close_now, 2),
        spring=spring_signal,
        pullback=pullback_signal,
        bounce=bounce_signal,
        breakout=breakout_signal,
        bullish_consensus=bullish_consensus,
        atr_pct=round(atr_pct, 3),
    )

    return ScalperFeatures(
        token=token,
        tf="5m",
        spot_price=close_now,
        twap_30m=twap_30m,
        close=close_now,
        atr_pct=atr_pct,
        spring_signal=spring_signal,
        pullback_signal=pullback_signal,
        bounce_signal=bounce_signal,
        breakout_signal=breakout_signal,
        has_structure=has_structure,
        is_ranging=is_ranging,
        is_bullish=is_bullish,
        btc_change_20b=btc_change_20b,
        bullish_consensus=bullish_consensus,
        relative_strength=relative_strength,
        use_rel_strength=use_rel_strength,
        setup_weights=setup_weights,
        consec_losses=0,
        daily_pnl_pct=0.0,
        in_cooldown=False,
    )
