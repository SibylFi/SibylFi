"""
Inference helper for Research Agents.

Tries 0G Compute first (per provider rotation list), falls back to Anthropic
if USE_FALLBACK_INFERENCE=1, returns a deterministic stub if MOCK_MODE=1.

The deterministic stub is critical for end-to-end testing — it lets the same
prompt produce the same output every time so the rest of the pipeline can be
asserted on.
"""
import asyncio
import hashlib
from dataclasses import dataclass
from typing import Optional

import structlog
from openai import AsyncOpenAI

from .settings import get_settings

log = structlog.get_logger(__name__)


@dataclass
class InferenceResult:
    text: str
    model: str
    backend: str  # "0g" | "anthropic" | "mock"


# Provider rotation list — extend as more providers come online
_OG_PROVIDERS = [
    {"endpoint_env": "OG_COMPUTE_ENDPOINT", "key_env": "OG_COMPUTE_API_KEY", "model_env": "OG_COMPUTE_MODEL"},
]


async def infer(prompt: str, *, persona: str = "default", max_tokens: int = 256) -> InferenceResult:
    """Returns inference text. In MOCK_MODE, returns a deterministic stub."""
    settings = get_settings()

    if settings.MOCK_MODE:
        return _mock_inference(prompt, persona, max_tokens)

    if settings.USE_FALLBACK_INFERENCE:
        return await _anthropic_inference(prompt, max_tokens)

    # Try 0G providers in order
    last_err: Optional[Exception] = None
    for provider in _OG_PROVIDERS:
        try:
            return await _og_inference(prompt, provider, max_tokens)
        except Exception as e:
            last_err = e
            log.warning("og_provider_failed", error=str(e))

    # All 0G providers down — fall back to Anthropic
    log.warning("og_all_failed_falling_back_anthropic")
    return await _anthropic_inference(prompt, max_tokens)


def _mock_inference(prompt: str, persona: str, max_tokens: int) -> InferenceResult:
    """
    Deterministic mock — same prompt + persona always returns same output.
    Used for offline development and reproducible tests.
    """
    seed = hashlib.sha256((persona + prompt).encode()).hexdigest()
    # Pick a directional bias and confidence from the seed
    direction = "long" if int(seed[:2], 16) > 127 else "short"
    confidence = 5000 + int(seed[2:6], 16) % 4000  # 5000-9000 bps

    persona_voice = {
        "meanrev": "Reversion thesis active; price extension exceeds 2σ from rolling mean.",
        "momentum": "Trend continuation indicated; 4h close above prior breakout band.",
        "news": "Sentiment delta positive on token mentions in last 30min; volume confirms.",
        "default": "Signal conditions met."
    }.get(persona, "Signal conditions met.")

    text = (
        f"DIRECTION: {direction.upper()}\n"
        f"CONFIDENCE_BPS: {confidence}\n"
        f"THESIS: {persona_voice}"
    )
    return InferenceResult(text=text, model="mock-deterministic", backend="mock")


async def _og_inference(prompt: str, provider: dict, max_tokens: int) -> InferenceResult:
    """Calls 0G Compute via OpenAI-compatible endpoint."""
    settings = get_settings()

    client = AsyncOpenAI(
        base_url=settings.OG_COMPUTE_ENDPOINT,
        api_key=settings.OG_COMPUTE_API_KEY,
        timeout=15.0,
    )
    response = await client.chat.completions.create(
        model=settings.OG_COMPUTE_MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
    )
    return InferenceResult(
        text=response.choices[0].message.content or "",
        model=settings.OG_COMPUTE_MODEL,
        backend="0g",
    )


async def _anthropic_inference(prompt: str, max_tokens: int) -> InferenceResult:
    """Falls back to Anthropic API."""
    from anthropic import AsyncAnthropic
    settings = get_settings()

    client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    response = await client.messages.create(
        model="claude-sonnet-4-6-20250515",
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )

    text = ""
    for block in response.content:
        if hasattr(block, "text"):
            text += block.text

    return InferenceResult(text=text, model="claude-sonnet-4-6", backend="anthropic")
