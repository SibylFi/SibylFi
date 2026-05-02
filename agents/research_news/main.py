"""
Herald — event telemancer.

Thesis: every announcement is an echo. Triggers on sentiment delta in
recent token mentions.
"""
from agents.shared.base_research_agent import PersonaConfig
from agents.shared.research_app_factory import build_research_app
from agents.shared.settings import get_settings

settings = get_settings()

PERSONA = PersonaConfig(
    name="news",
    ens_name="herald.sibyl.eth",
    private_key=settings.RESEARCH_NEWS_KEY,
    price_per_signal_usdc=1.20,
    horizon_seconds=1800,  # 30 minutes
    prompt_template=(
        "You are a news-driven trading oracle. Analyze {token} at price {reference_price}.\n"
        "Sentiment delta over the last 30 minutes is your primary signal.\n"
        "Output ONLY in this format:\n"
        "DIRECTION: <LONG|SHORT>\n"
        "CONFIDENCE_BPS: <integer 0-10000>\n"
        "THESIS: <one sentence>\n"
    ),
)

app = build_research_app(PERSONA)
