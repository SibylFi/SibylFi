"""
Uniswap V3 TWAP reader.

In real mode, calls pool.observe() on Base Sepolia for a 5-minute window
ending at horizon-end.

In MOCK_MODE, reads from agents/shared/mocks/twap_fixtures.json keyed by
token + horizon.
"""
from __future__ import annotations

import json
from pathlib import Path

import structlog

from agents.shared.settings import get_settings

log = structlog.get_logger(__name__)

FIXTURES_PATH = Path(__file__).resolve().parent.parent / "shared" / "mocks" / "twap_fixtures.json"


def read_twap_at_horizon(token: str, horizon_seconds: int) -> float:
    """Returns the TWAP price at horizon-end."""
    settings = get_settings()

    if settings.MOCK_MODE:
        return _mock_twap(token, horizon_seconds)

    raise NotImplementedError(
        "Real Uniswap V3 TWAP read not implemented in scaffold. "
        "Use Web3 + IUniswapV3PoolDerivedState.observe() against the highest-TVL "
        "(token, USDC) pool on Base Sepolia. See specs/signal-validator.md."
    )


def _mock_twap(token: str, horizon_seconds: int) -> float:
    fixtures = json.loads(FIXTURES_PATH.read_text())
    if token not in fixtures:
        log.warning("twap_fixture_missing_token", token=token)
        return 1.0

    horizons = fixtures[token]["horizons"]
    horizon_str = str(horizon_seconds)
    if horizon_str in horizons:
        return horizons[horizon_str]["twap"]

    # If exact horizon not in fixtures, return the closest
    closest = min(horizons.keys(), key=lambda h: abs(int(h) - horizon_seconds))
    return horizons[closest]["twap"]
