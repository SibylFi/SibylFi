"""
Reversal — mean-reversion oracle.

Thesis: what overshoots must return. Triggers on RSI extremes outside
2σ from the rolling mean.
"""
from agents.shared.base_research_agent import PersonaConfig
from agents.shared.research_app_factory import build_research_app
from agents.shared.settings import get_settings

settings = get_settings()

PERSONA = PersonaConfig(
    name="meanrev",
    ens_name="reversal.sibyl.eth",
    private_key=settings.RESEARCH_MEANREV_KEY,
    price_per_signal_usdc=0.50,
    horizon_seconds=3600,  # 1 hour
    prompt_template=(
        "You are a mean-reversion trading oracle. Analyze {token} at price {reference_price}.\n"
        "Output ONLY in this format:\n"
        "DIRECTION: <LONG|SHORT>\n"
        "CONFIDENCE_BPS: <integer 0-10000>\n"
        "THESIS: <one sentence>\n"
    ),
)

app = build_research_app(PERSONA)
