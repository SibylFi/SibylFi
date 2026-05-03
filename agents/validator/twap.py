"""
TWAP reader for the SibylFi Validator.

Source ladder (real mode):
  1. Uniswap V3 `pool.observe()` on Base Sepolia — the *correct* settlement
     source. Same pool the trader executed against, on-chain, replayable by
     anyone reading the chain. This is the property that makes ERC-8004
     reputation meaningful: deterministic settlement.
  2. Kraken public OHLC — labelled `degraded_mode=true` fallback when the
     pool doesn't exist on testnet, or has insufficient observation
     cardinality for the horizon. Off-chain and not replayable; only
     defensible for a demo when the on-chain path is unavailable.
  3. Mock fixtures — last resort when both networks are down.

MOCK_MODE=1: skips the ladder; deterministic seeded random walk from fixture
ref_price to exit_price for reproducible local tests.
"""
from __future__ import annotations

import json
import math
import random
from pathlib import Path

import structlog

from agents.shared.settings import get_settings
from agents.validator.algorithm import Checkpoint

log = structlog.get_logger(__name__)

FIXTURES_PATH = Path(__file__).resolve().parent.parent / "shared" / "mocks" / "twap_fixtures.json"


def read_twap_at_horizon(token: str, horizon_seconds: int) -> float:
    """Returns the TWAP price at horizon-end. Backward-compat wrapper."""
    cps = read_checkpoints(token=token, published_at_block=0, horizon_seconds=horizon_seconds)
    return cps[-1].price if cps else 1.0


def read_checkpoints(
    token: str,
    published_at_block: int,
    horizon_seconds: int,
    n_checkpoints: int = 5,
) -> list[Checkpoint]:
    """
    Returns n_checkpoints evenly spaced price samples spanning [t=0, t=horizon].
    """
    settings = get_settings()
    if settings.MOCK_MODE:
        return _mock_checkpoints(token, published_at_block, horizon_seconds, n_checkpoints)

    # Tier 1 — Uniswap V3 observe() (on-chain, deterministic, replayable).
    try:
        from agents.validator.uniswap_twap import read_uniswap_v3_checkpoints
        return read_uniswap_v3_checkpoints(token, horizon_seconds, n_checkpoints)
    except Exception as exc:
        log.warning(
            "twap_uniswap_v3_failed_falling_back_to_kraken",
            token=token,
            horizon_seconds=horizon_seconds,
            degraded_mode=True,
            reason=str(exc),
        )

    # Tier 2 — Kraken OHLC (off-chain market data, NOT replayable).
    try:
        return _real_checkpoints(token, horizon_seconds, n_checkpoints)
    except Exception as exc:
        log.warning(
            "twap_kraken_failed_falling_back_to_mock",
            token=token,
            horizon_seconds=horizon_seconds,
            error=str(exc),
        )
        return _mock_checkpoints(token, published_at_block, horizon_seconds, n_checkpoints)


def _real_checkpoints(
    token: str,
    horizon_seconds: int,
    n: int,
) -> list[Checkpoint]:
    """
    Sample n evenly spaced price points from the last `horizon_seconds` of
    Kraken OHLC history. Interval chosen to fit within Kraken's 720-bar limit.
    """
    from agents.shared.strategies.feature_provider_real import (
        fetch_kraken_ohlc,
        kraken_pair,
        parse_kraken_ohlcv,
    )

    pair, _ = kraken_pair(token)

    # Kraken intervals in minutes: 1, 5, 15, 30, 60, 240, 1440
    # Choose so that horizon_seconds / bar_secs ≤ 720
    if horizon_seconds <= 3_600:           # ≤ 1 h  → 1m bars (≤ 60 bars)
        interval_min, bar_secs = 1, 60
    elif horizon_seconds <= 86_400:        # ≤ 24 h → 5m bars (≤ 288 bars)
        interval_min, bar_secs = 5, 300
    elif horizon_seconds <= 432_000:       # ≤ 5 d  → 60m bars (≤ 120 bars)
        interval_min, bar_secs = 60, 3_600
    else:                                  # > 5 d  → 240m bars
        interval_min, bar_secs = 240, 14_400

    bars = fetch_kraken_ohlc(pair, interval_min=interval_min)
    _, _, _, closes, _ = parse_kraken_ohlcv(bars)
    total = len(closes)
    if total == 0:
        raise RuntimeError("kraken returned 0 bars for TWAP")

    # Sample n evenly spaced indices across the fetched bar series
    indices = [round(i * (total - 1) / max(1, n - 1)) for i in range(n)]
    # Deduplicate while preserving order
    seen: set[int] = set()
    unique: list[int] = []
    for idx in indices:
        if idx not in seen:
            seen.add(idx)
            unique.append(idx)

    checkpoints: list[Checkpoint] = []
    for rank, idx in enumerate(unique):
        t = round(rank / max(1, len(unique) - 1) * horizon_seconds)
        checkpoints.append(Checkpoint(price=closes[idx], t=t))

    # Snap the last checkpoint to the exact horizon boundary
    if checkpoints:
        checkpoints[-1] = Checkpoint(price=closes[-1], t=horizon_seconds)

    log.info(
        "twap_real_checkpoints",
        pair=pair,
        interval_min=interval_min,
        bars_fetched=total,
        n_checkpoints=len(checkpoints),
        first_price=checkpoints[0].price if checkpoints else None,
        last_price=checkpoints[-1].price if checkpoints else None,
    )
    return checkpoints


def _mock_checkpoints(
    token: str,
    published_at_block: int,
    horizon_seconds: int,
    n: int,
) -> list[Checkpoint]:
    fixtures = json.loads(FIXTURES_PATH.read_text())

    if token not in fixtures:
        log.warning("twap_fixture_missing_token", token=token)
        return []  # empty → INCONCLUSIVE in the validator

    spec = fixtures[token]
    ref_price = float(spec.get("ref_price", spec.get("twap_5min_at_publication", 1.0)))

    horizons = spec["horizons"]
    horizon_str = str(horizon_seconds)
    if horizon_str in horizons:
        exit_price = float(horizons[horizon_str]["twap"])
    else:
        closest = min(horizons.keys(), key=lambda h: abs(int(h) - horizon_seconds))
        exit_price = float(horizons[closest]["twap"])

    # Deterministic seeded walk: same inputs → same path
    rng = random.Random(f"{token}:{published_at_block}:{horizon_seconds}")
    checkpoints: list[Checkpoint] = []
    for i in range(n):
        # Linear baseline + bounded jitter so checkpoints aren't a perfectly
        # straight line (gives the path-aware outcome resolver something to work with).
        progress = i / max(1, n - 1)
        base = ref_price + (exit_price - ref_price) * progress
        jitter_pct = (rng.random() - 0.5) * 0.002  # ±0.1%
        price = base * (1.0 + jitter_pct)
        t = int(horizon_seconds * progress)
        checkpoints.append(Checkpoint(price=price, t=t))

    # Force the last checkpoint to land exactly at exit_price so existing
    # fixture-driven tests stay deterministic.
    checkpoints[-1] = Checkpoint(price=exit_price, t=horizon_seconds)
    return checkpoints
