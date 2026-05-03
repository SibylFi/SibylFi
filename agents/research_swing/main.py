"""
Research Agent — Swing Trader (4H/1D).

Codename: Cartagena Onchain LONG PRO Trend Hunter.

Spec: agents/agent-research-swing.md. Strategy: agents/shared/strategies/swing.py.
The persona contributes only ENS identity, x402 price, params, and the
calibrator prompt template — all decision logic lives in `evaluate_swing`.
"""
from agents.shared.base_research_agent import PersonaConfig
from agents.shared.research_app_factory import build_research_app
from agents.shared.settings import get_settings
from agents.shared.strategies.snapshot import SwingParams

settings = get_settings()

PERSONA = PersonaConfig(
    name="swing",
    profile="swing",
    ens_name="swing.sibylfi.eth",
    private_key=settings.RESEARCH_MEANREV_KEY,    # reuse existing funded wallet
    price_per_signal_usdc=1.50,
    swing_params=SwingParams(),
    prompt_template=(
        "You are calibrating a deterministic SWING trading signal — direction "
        "and base levels are already fixed by the rule engine. Your job is to "
        "advise a small confidence delta in basis points based on the named "
        "setup, then write one short thesis sentence.\n\n"
        "Token: {token}\n"
        "Profile: {profile}\n"
        "Setup: {setup}\n"
        "Reference price (TWAP30): {reference_price}\n"
        "Target: {target_price}\n"
        "Stop: {stop_price}\n"
        "Horizon (s): {horizon_seconds}\n"
        "Base confidence (bps): {confidence_base}\n"
        "Cap (bps): {confidence_cap}\n\n"
        "Output EXACTLY two lines:\n"
        "CONFIDENCE_DELTA: <signed integer in [-300, +300]>\n"
        "THESIS: <one sentence, no newlines>\n"
    ),
)

app = build_research_app(PERSONA)
