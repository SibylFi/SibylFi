"""
Centralized settings, loaded from environment variables.

All agents import from here. Never read os.environ directly in agent code.
"""
from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # Operational
    MOCK_MODE: bool = True
    USE_FALLBACK_INFERENCE: bool = False
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # Networks
    SEPOLIA_RPC: str = "https://eth-sepolia.public.blastapi.io"
    BASE_SEPOLIA_RPC: str = "https://base-sepolia-rpc.publicnode.com"
    OG_GALILEO_RPC: str = "https://evmrpc-testnet.0g.ai"

    # Chain IDs
    CHAIN_ID_SEPOLIA: int = 11155111
    CHAIN_ID_BASE_SEPOLIA: int = 84532
    CHAIN_ID_GALILEO: int = 16601

    # Wallets — one per agent role
    RESEARCH_MEANREV_KEY: str = "0x" + "01" * 32
    RESEARCH_MOMENTUM_KEY: str = "0x" + "02" * 32
    RESEARCH_NEWS_KEY: str = "0x" + "03" * 32
    TRADING_KEY: str = "0x" + "04" * 32
    RISK_KEY: str = "0x" + "05" * 32
    VALIDATOR_KEY: str = "0x" + "06" * 32

    # x402
    COINBASE_CDP_KEY: str = "MOCK_CDP_KEY"
    X402_FACILITATOR_URL: str = "https://facilitator.cdp.coinbase.com"
    # When set, requests carrying this token bypass the CDP facilitator call so
    # the demo can run without a live x402 subscription.  Leave empty in prod.
    X402_DEMO_TOKEN: str = "demo-mock-token"

    # Inference
    ANTHROPIC_API_KEY: str = "MOCK_ANTHROPIC_KEY"
    OG_BROKER_KEY: str = "0x" + "07" * 32
    OG_COMPUTE_ENDPOINT: str = "https://provider.0g.example/v1"
    OG_COMPUTE_API_KEY: str = "MOCK_OG_KEY"
    OG_COMPUTE_MODEL: str = "qwen3.6-plus"

    # Database
    POSTGRES_HOST: str = "postgres"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "sibylfi"
    POSTGRES_USER: str = "sibylfi"
    POSTGRES_PASSWORD: str = "sibylfi-dev-password"

    # Redis
    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379

    # Sidecar
    SIDECAR_0G_STORAGE_URL: str = "http://sidecar-0gstorage:7000"

    # Uniswap
    UNISWAP_API_KEY: str = "MOCK_UNISWAP_KEY"
    UNISWAP_TRADING_API_BASE: str = "https://trade-api.gateway.uniswap.org"

    # Token addresses on Base Sepolia
    USDC_BASE_SEPOLIA: str = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"
    WETH_BASE_SEPOLIA: str = "0x4200000000000000000000000000000000000006"

    @property
    def database_url(self) -> str:
        return (
            f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def redis_url(self) -> str:
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/0"


@lru_cache
def get_settings() -> Settings:
    return Settings()
