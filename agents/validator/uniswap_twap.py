"""
Uniswap V3 on-chain TWAP reader for the SibylFi Validator.

This is the *correct* settlement source: prices come from the same pool the
trader executed against, sampled via `IUniswapV3Pool.observe()`, so anyone
replaying the chain produces the same checkpoints. Replay-deterministic
settlement is the property that makes ERC-8004 reputation meaningful.

Failure modes (all fall back to Kraken upstream, with degraded_mode logged):
  - factory.getPool returns 0x0 (no pool deployed for this pair/fee)
  - pool.observe reverts with "OLD" (insufficient observation cardinality
    for the requested horizon — pool needs increaseObservationCardinalityNext)
  - RPC unreachable

Sampling pattern: each checkpoint is a 60-second TWAP centred on the target
timestamp. Single-block manipulation can't move a 60-s TWAP meaningfully.
"""
from __future__ import annotations

from typing import Tuple

import structlog
from web3 import Web3

from agents.shared.settings import get_settings
from agents.validator.algorithm import Checkpoint

log = structlog.get_logger(__name__)

# Minimal ABIs — only the methods the validator needs.
_FACTORY_ABI = [{
    "inputs": [
        {"internalType": "address", "name": "tokenA", "type": "address"},
        {"internalType": "address", "name": "tokenB", "type": "address"},
        {"internalType": "uint24",  "name": "fee",    "type": "uint24"},
    ],
    "name": "getPool",
    "outputs": [{"internalType": "address", "name": "pool", "type": "address"}],
    "stateMutability": "view",
    "type": "function",
}]

_POOL_ABI = [
    {
        "inputs": [{"internalType": "uint32[]", "name": "secondsAgos", "type": "uint32[]"}],
        "name": "observe",
        "outputs": [
            {"internalType": "int56[]",   "name": "tickCumulatives",                   "type": "int56[]"},
            {"internalType": "uint160[]", "name": "secondsPerLiquidityCumulativeX128", "type": "uint160[]"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "token0",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "token1",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
]

# Window length (seconds) for each checkpoint TWAP. 60 s is the canonical
# anti-MEV minimum; long enough to swallow a single-block flash, short enough
# to track real moves over the horizon.
_CHECKPOINT_WINDOW_SECS = 60


def _pair_for_token(token: str) -> Tuple[str, str, int, int]:
    """
    Return (tokenA, tokenB, decimalsA, decimalsB) for a SibylFi token pair string.
    tokenA is the *quote* asset (what we want price of), tokenB is the *base*.
    For 'WETH/USDC' we want USDC-per-WETH, so tokenA=WETH, tokenB=USDC.
    """
    s = get_settings()
    if token.upper() in ("WETH/USDC", "ETH/USDC", "ETH"):
        return s.WETH_BASE_SEPOLIA, s.USDC_BASE_SEPOLIA, 18, 6
    raise ValueError(f"uniswap_twap: unsupported token pair {token!r}")


def _tick_to_price(tick: int, token0: str, token1: str, dec0: int, dec1: int,
                   weth_addr: str) -> float:
    """
    Convert a Uniswap V3 tick to USDC-per-WETH (display units), accounting for
    token ordering and decimals.

    Raw price (token1 per token0, in raw integer amounts) = 1.0001 ** tick.
    Display price (token1 per token0, decimal-adjusted) = raw * 10^(dec0 - dec1).
    """
    raw = 1.0001 ** tick
    if token0.lower() == weth_addr.lower():
        # token0 = WETH, token1 = USDC → raw = USDC_raw / WETH_raw → display = USDC/WETH
        return raw * (10 ** (dec0 - dec1))
    else:
        # token0 = USDC, token1 = WETH → raw = WETH_raw / USDC_raw → invert
        # display USDC/WETH = 1 / (raw * 10^(dec0 - dec1))
        return (10 ** (dec1 - dec0)) / raw


def read_uniswap_v3_checkpoints(
    token: str,
    horizon_seconds: int,
    n_checkpoints: int = 5,
) -> list[Checkpoint]:
    """
    Sample n_checkpoints prices evenly spaced across [now - horizon, now].
    Each checkpoint is a 60-second TWAP ending at that timestamp.

    Raises on any failure — caller falls back to Kraken / mock.
    """
    if n_checkpoints < 2:
        raise ValueError("n_checkpoints must be ≥ 2")

    s = get_settings()
    w3 = Web3(Web3.HTTPProvider(s.BASE_SEPOLIA_RPC))
    if not w3.is_connected():
        raise RuntimeError(f"base sepolia rpc unreachable: {s.BASE_SEPOLIA_RPC}")

    token_a, token_b, dec_a, dec_b = _pair_for_token(token)
    factory = w3.eth.contract(
        address=Web3.to_checksum_address(s.UNISWAP_V3_FACTORY_BASE_SEPOLIA),
        abi=_FACTORY_ABI,
    )
    pool_addr = factory.functions.getPool(
        Web3.to_checksum_address(token_a),
        Web3.to_checksum_address(token_b),
        s.UNISWAP_V3_FEE_TIER,
    ).call()
    if int(pool_addr, 16) == 0:
        raise RuntimeError(
            f"no uniswap v3 pool for {token} fee={s.UNISWAP_V3_FEE_TIER} "
            f"on base sepolia"
        )

    pool = w3.eth.contract(address=pool_addr, abi=_POOL_ABI)
    token0 = pool.functions.token0().call()
    token1 = pool.functions.token1().call()
    # decimals follow whichever side WETH ended up on
    if token0.lower() == s.WETH_BASE_SEPOLIA.lower():
        dec0, dec1 = 18, 6
    else:
        dec0, dec1 = 6, 18

    # Build secondsAgos: for each checkpoint i in [0..n-1] we need two points,
    # the start and end of a 60-s window centred on t_ago_i.
    #   t_ago_i = horizon * (n-1-i) / (n-1)   (older first → newest last)
    # Each window: [t_ago_i + 30, max(t_ago_i - 30, 0)]; clamp the latest one to 0.
    half = _CHECKPOINT_WINDOW_SECS // 2
    starts: list[int] = []
    ends:   list[int] = []
    for i in range(n_checkpoints):
        t_ago = round(horizon_seconds * (n_checkpoints - 1 - i) / (n_checkpoints - 1))
        start_ago = t_ago + half
        end_ago = max(t_ago - half, 0)
        starts.append(start_ago)
        ends.append(end_ago)

    # observe() takes one flat array; pack as [s0, e0, s1, e1, ...]
    seconds_agos = []
    for s_, e_ in zip(starts, ends):
        seconds_agos.extend([s_, e_])

    tick_cums, _ = pool.functions.observe(seconds_agos).call()

    weth_addr = s.WETH_BASE_SEPOLIA
    checkpoints: list[Checkpoint] = []
    for i, (s_ago, e_ago) in enumerate(zip(starts, ends)):
        cum_start = tick_cums[2 * i]
        cum_end   = tick_cums[2 * i + 1]
        dt = s_ago - e_ago
        if dt <= 0:
            raise RuntimeError(f"invalid window dt={dt} for checkpoint {i}")
        # Tick math: arithmetic mean tick = (cum_end - cum_start) / dt.
        # Per V3 spec, integer-divide rounded toward negative infinity for
        # negative quotients, but for our resolution (1-tick) the float result
        # is fine — settlement depends on the price not the exact tick.
        avg_tick = (cum_end - cum_start) / dt
        price = _tick_to_price(int(avg_tick), token0, token1, dec0, dec1, weth_addr)
        # t inside the signal's horizon window: t=0 oldest, t=horizon newest.
        t_in_horizon = round(horizon_seconds * i / (n_checkpoints - 1))
        checkpoints.append(Checkpoint(price=price, t=t_in_horizon))

    log.info(
        "uniswap_v3_twap_checkpoints",
        token=token,
        pool=pool_addr,
        horizon_seconds=horizon_seconds,
        n=len(checkpoints),
        first_price=checkpoints[0].price,
        last_price=checkpoints[-1].price,
    )
    return checkpoints
