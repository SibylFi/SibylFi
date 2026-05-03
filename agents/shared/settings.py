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
    # Public testnet facilitator (no auth, supports base-sepolia x402v1 exact).
    # Coinbase CDP key is only required for mainnet networks via the CDP-hosted
    # facilitator and is unused on Base Sepolia.
    COINBASE_CDP_KEY: str = ""
    X402_FACILITATOR_URL: str = "https://facilitator.x402.rs"
    # x402 network identifier for the asset paid in (USDC on Base Sepolia).
    X402_NETWORK: str = "base-sepolia"
    # Escape hatch for demo-mode bypass. The middleware honours it ONLY when
    # MOCK_MODE=1 OR FORCE_X402_DEMO=1 — never silently in real mode.
    X402_DEMO_TOKEN: str = ""
    FORCE_X402_DEMO: bool = False

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

    # Mainnet token addresses — used ONLY by the Trading API shadow quote for
    # the same pair (Uniswap's hosted Trading API doesn't support testnets).
    USDC_MAINNET: str = "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"
    WETH_MAINNET: str = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"
    CHAIN_ID_ETHEREUM: int = 1

    # Uniswap V3 — used by Validator for on-chain TWAP settlement.
    # Factory address is the canonical V3 deployment on Base Sepolia. The
    # validator calls factory.getPool(token0, token1, fee) → pool, then
    # pool.observe([secondsAgos]) for deterministic settlement. Falls back to
    # Kraken (clearly logged as degraded_mode) when no pool exists or the pool
    # has insufficient observation cardinality for the requested horizon.
    UNISWAP_V3_FACTORY_BASE_SEPOLIA: str = "0x4752ba5DBc23f44D87826276BF6Fd6b1C372aD24"
    UNISWAP_V3_FEE_TIER: int = 500   # 0.05% — canonical for WETH/USDC

    # Uniswap V3 router/quoter for direct on-chain swaps. Uniswap's hosted
    # Trading API does not support testnets (returns ResourceNotFound on Base
    # Sepolia), so the Trading Agent calls SwapRouter02 directly.
    UNISWAP_V3_SWAP_ROUTER02_BASE_SEPOLIA: str = "0x94cC0AaC535CCDB3C01d6787D6413C739ae12bc4"
    UNISWAP_V3_QUOTER_V2_BASE_SEPOLIA: str = "0xC5290058841028F1614F3A6F0F5816cAd0df5E27"
    SWAP_SLIPPAGE_BPS: int = 50      # 0.5% — minOut tolerance on exactInputSingle
    SWAP_DEADLINE_SECONDS: int = 300

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
