"""
Feature provider — produces a strategy snapshot for a token.

In MOCK_MODE we read pre-baked snapshots from `mock_features.json` (deterministic,
always passes strategy gates — good for demo scripting and unit tests).

In real mode we fetch live OHLCV from Binance public API and run indicators.py.
If the real pipeline fails (network error, rate limit, parse error) we fall back
to mock and log degraded mode so the demo never hard-blocks.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

import structlog

from agents.shared.settings import get_settings
from agents.shared.strategies.snapshot import ScalperFeatures, SwingFeatures

log = structlog.get_logger(__name__)

_FIXTURE = Path(__file__).resolve().parent / "mock_features.json"

Profile = Literal["swing", "scalper"]


def load_features(profile: Profile, token: str) -> SwingFeatures | ScalperFeatures:
    settings = get_settings()
    if settings.MOCK_MODE:
        return _load_mock(profile, token)

    try:
        from agents.shared.strategies.feature_provider_real import load_features_real
        return load_features_real(profile, token)
    except Exception as exc:
        log.warning(
            "feature_provider_real_failed_falling_back_to_mock",
            profile=profile,
            token=token,
            error=str(exc),
        )
        return _load_mock(profile, token)


def _load_mock(profile: Profile, token: str) -> SwingFeatures | ScalperFeatures:
    raw = json.loads(_FIXTURE.read_text())
    if profile not in raw:
        raise ValueError(f"unknown profile: {profile}")

    bucket = raw[profile]
    snap = bucket.get(token) or bucket["_default"]
    cleaned = {k: v for k, v in snap.items() if not k.startswith("_")}

    if profile == "swing":
        return SwingFeatures(**cleaned)
    return ScalperFeatures(**cleaned)
