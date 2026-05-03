"""
Base Research Agent — v2.

The persona-specific code is reduced to: choose a profile (swing | scalper),
provide tuning params, and write a calibrator prompt template. Everything
else (feature loading, strategy evaluation, LLM calibration, signing,
x402 paywall, persistence) is shared.

Decision flow:
  1. Load features for `token` from the feature provider (MOCK_MODE-aware).
  2. Run `evaluate_swing` or `evaluate_scalper`.
  3. If the strategy rejects → return None; the route turns this into 204.
  4. Otherwise call the LLM (mock or 0G) ONLY to:
       - emit a confidence delta in [-1000, +1000] bps, and
       - write a 1-sentence thesis.
     The LLM cannot flip direction (long-only at schema layer) and cannot
     reject signals (the strategy already accepted).
  5. confidence_final = clamp(strategy_base + llm_delta, 0, strategy_cap).
  6. Build, sign, persist, return.
"""
from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from typing import Literal

import structlog
from eth_account import Account

from agents.shared.db import db_conn
from agents.shared.inference import infer
from agents.shared.settings import get_settings
from agents.shared.signal_schema import EntryCondition, Signal
from agents.shared.signing import sign_signal
from agents.shared.strategies.feature_provider import load_features
from agents.shared.strategies.scalper import evaluate_scalper
from agents.shared.strategies.snapshot import (
    ScalperFeatures,
    ScalperParams,
    StrategyResult,
    SwingFeatures,
    SwingParams,
)
from agents.shared.strategies.swing import evaluate_swing

log = structlog.get_logger(__name__)

Profile = Literal["swing", "scalper"]


@dataclass
class PersonaConfig:
    name: str                                # short id, e.g. "swing"
    profile: Profile                         # which strategy to run
    ens_name: str                            # e.g. "swing.sibyl.eth"
    private_key: str
    price_per_signal_usdc: float
    prompt_template: str                     # for the LLM calibrator
    swing_params: SwingParams | None = None
    scalper_params: ScalperParams | None = None


class BaseResearchAgent:
    def __init__(self, persona: PersonaConfig):
        self.persona = persona
        self.settings = get_settings()
        self.address = Account.from_key(persona.private_key).address
        # Last strategy evaluation; the API layer reads this after generate_signal
        # returns None to surface the rejection reason to the caller.
        self.last_strategy_result: StrategyResult | None = None

    # ── Public entrypoint ────────────────────────────────────────────────

    async def generate_signal(
        self,
        token: str,
        published_at_block: int,
    ) -> Signal | None:
        features = load_features(self.persona.profile, token)
        result = self._evaluate(features)
        self.last_strategy_result = result

        if not result.accept:
            log.info(
                "strategy_rejected",
                persona=self.persona.name,
                profile=self.persona.profile,
                token=token,
                reason=result.reason,
            )
            return None

        delta, thesis, backend = await self._calibrate(token, result)

        cap = result.confidence_bps_cap or 10000
        base = result.confidence_bps_base or 0
        confidence_final = max(0, min(cap, base + delta))

        signal = self._build_and_sign(
            token=token,
            result=result,
            confidence_bps=confidence_final,
            thesis=thesis,
            published_at_block=published_at_block,
        )

        log.info(
            "signal_generated",
            signal_id=signal.signal_id,
            persona=self.persona.name,
            profile=self.persona.profile,
            setup=result.setup,
            confidence_bps=confidence_final,
            confidence_base=base,
            confidence_delta=delta,
            target=signal.target_price,
            stop=signal.stop_price,
            horizon=signal.horizon_seconds,
            backend=backend,
        )

        await self._persist(signal)
        return signal

    # ── Strategy dispatch ────────────────────────────────────────────────

    def _evaluate(self, features) -> StrategyResult:
        if self.persona.profile == "swing":
            assert isinstance(features, SwingFeatures)
            return evaluate_swing(features, self.persona.swing_params)
        if self.persona.profile == "scalper":
            assert isinstance(features, ScalperFeatures)
            return evaluate_scalper(features, self.persona.scalper_params)
        raise ValueError(f"unknown profile: {self.persona.profile}")

    # ── LLM calibrator (advisory only) ───────────────────────────────────

    async def _calibrate(
        self,
        token: str,
        result: StrategyResult,
    ) -> tuple[int, str, str]:
        """Returns (confidence_delta_bps, thesis, backend)."""
        prompt = self.persona.prompt_template.format(
            token=token,
            profile=self.persona.profile,
            setup=result.setup,
            confidence_base=result.confidence_bps_base,
            confidence_cap=result.confidence_bps_cap,
            reference_price=result.reference_price,
            target_price=result.target_price,
            stop_price=result.stop_price,
            horizon_seconds=result.horizon_seconds,
        )
        out = await infer(prompt, persona=self.persona.name, max_tokens=256)
        delta, thesis = _parse_calibration(out.text)
        return delta, thesis, out.backend

    # ── Signal construction ──────────────────────────────────────────────

    def _build_and_sign(
        self,
        *,
        token: str,
        result: StrategyResult,
        confidence_bps: int,
        thesis: str,
        published_at_block: int,
    ) -> Signal:
        signal_id = "0x" + secrets.token_hex(32)

        metadata = dict(result.metadata or {})
        metadata["thesis"] = thesis
        metadata["profile"] = self.persona.profile

        unsigned = Signal(
            signal_id=signal_id,
            publisher=self.persona.ens_name,
            token=token,
            direction="long",                          # schema-enforced
            entry_condition=EntryCondition(
                type="market_at_publication",
                reference_price=result.reference_price,
            ),
            target_price=round(result.target_price, 6),
            stop_price=round(result.stop_price, 6),
            horizon_seconds=result.horizon_seconds,
            confidence_bps=confidence_bps,
            published_at_block=published_at_block,
            metadata=metadata,
            signature="0x00",
        )

        sig_hex = sign_signal(unsigned, self.persona.private_key)
        return unsigned.model_copy(update={"signature": sig_hex})

    # ── Persistence ──────────────────────────────────────────────────────

    async def _persist(self, signal: Signal) -> None:
        async with db_conn() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO signals (
                        signal_id, publisher, publisher_addr, token, direction,
                        reference_price, target_price, stop_price,
                        horizon_seconds, confidence_bps,
                        horizon_expires_at, raw_payload
                    ) VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s, %s,
                        %s, %s,
                        NOW() + (%s || ' seconds')::interval,
                        %s
                    )
                    ON CONFLICT (signal_id) DO NOTHING
                    """,
                    (
                        signal.signal_id, signal.publisher, self.address,
                        signal.token, signal.direction,
                        signal.entry_condition.reference_price,
                        signal.target_price, signal.stop_price,
                        signal.horizon_seconds, signal.confidence_bps,
                        signal.horizon_seconds,
                        signal.model_dump_json(),
                    ),
                )
            await conn.commit()


# ─────────────────────────────────────────────────────────────────────────
# Calibration parsing
# ─────────────────────────────────────────────────────────────────────────

_DELTA_RE = re.compile(r"CONFIDENCE_DELTA:\s*([+\-]?\d{1,4})", re.IGNORECASE)
_THESIS_RE = re.compile(r"THESIS:\s*(.+?)(?:\n|$)", re.IGNORECASE | re.DOTALL)


def _parse_calibration(text: str) -> tuple[int, str]:
    """Parse the LLM calibrator's response.

    Expected (case-insensitive):
        CONFIDENCE_DELTA: <signed integer in bps>
        THESIS: <one sentence>

    Bounds: delta clamped to [-1000, +1000] so the LLM cannot dominate the
    rule-based base. Missing fields fall back to (0, "Calibration unavailable.").
    """
    m_delta = _DELTA_RE.search(text)
    m_thesis = _THESIS_RE.search(text)

    if m_delta:
        try:
            delta = int(m_delta.group(1))
        except ValueError:
            delta = 0
    else:
        delta = 0
    delta = max(-1000, min(1000, delta))

    thesis = m_thesis.group(1).strip() if m_thesis else "Calibration unavailable."
    return delta, thesis
