"""
Wave — momentum cartographer.

Thesis: trend continuation on 4h breakouts.
"""
from agents.shared.base_research_agent import PersonaConfig
from agents.shared.research_app_factory import build_research_app
from agents.shared.settings import get_settings

settings = get_settings()

PERSONA = PersonaConfig(
    name="momentum",
    ens_name="wave.sibyl.eth",
    private_key=settings.RESEARCH_MOMENTUM_KEY,
    price_per_signal_usdc=0.75,
    horizon_seconds=14400,  # 4 hours
    prompt_template=(
        "You are a momentum trading oracle. Analyze {token} at price {reference_price}.\n"
        "Output ONLY in this format:\n"
        "DIRECTION: <LONG|SHORT>\n"
        "CONFIDENCE_BPS: <integer 0-10000>\n"
        "THESIS: <one sentence>\n"
    ),
)

app = build_research_app(PERSONA)
