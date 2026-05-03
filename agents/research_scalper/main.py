"""
Research Agent — Scalper Adaptive (1m/5m).

Codename: Cartagena Onchain SibylFi LONG Adaptive v4.

Spec: agents/agent-research-scalper.md. Strategy: agents/shared/strategies/scalper.py.
Multi-setup adaptive ML with anti-DD + multi-asset filter, all enforced by
`evaluate_scalper`. The LLM is called only as a confidence calibrator.
"""
from agents.shared.base_research_agent import PersonaConfig
from agents.shared.research_app_factory import build_research_app
from agents.shared.settings import get_settings
from agents.shared.strategies.snapshot import ScalperParams

settings = get_settings()

PERSONA = PersonaConfig(
    name="scalper",
    profile="scalper",
    ens_name="scalper.sibyl.eth",
    private_key=settings.RESEARCH_MOMENTUM_KEY,   # reuse existing funded wallet
    price_per_signal_usdc=0.50,
    scalper_params=ScalperParams(mode="Balanced"),
    prompt_template=(
        "You are calibrating a deterministic SCALPER trading signal — the "
        "rule engine already chose the strongest active setup, multi-asset "
        "filter passed, and base levels are fixed. Suggest a small confidence "
        "delta in basis points and one short thesis sentence.\n\n"
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
