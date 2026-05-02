"""
Smoke test for the validator algorithm.

Verifies that settle() and reputation_update() produce the expected outputs
on the canonical examples from specs/reputation-math.md §11.

Run: pytest agents/validator/test_algorithm.py -v
   or: python agents/validator/test_algorithm.py
"""
try:
    import pytest  # noqa: F401
except ImportError:
    pass  # standalone mode

from agents.shared.signal_schema import EntryCondition, Outcome, Signal
from agents.validator.algorithm import (
    ExecutionRecord,
    SettlementInputs,
    reputation_update,
    settle,
)


def make_signal(direction="long", ref=100.0, target=102.0, stop=99.0, horizon=3600):
    return Signal(
        signal_id="0x" + "ab" * 32,
        publisher="reversal.sibyl.eth",
        token="eip155:84532/erc20:0xWETH",
        direction=direction,
        entry_condition=EntryCondition(type="market_at_publication", reference_price=ref),
        target_price=target,
        stop_price=stop,
        horizon_seconds=horizon,
        confidence_bps=6500,
        published_at_block=12345678,
        signature="0x" + "00" * 65,
    )


def make_inputs(signal, twap, executions=None, publisher_addr="0xPUBLISHER"):
    return SettlementInputs(
        signal=signal,
        publisher_addr=publisher_addr,
        twap_at_horizon=twap,
        executions=executions or [],
        eth_usd_at_horizon=3450.0,
        base_sepolia_gas_price_wei=1_000_000_000,
        settled_at_block=12_345_900,
        settled_at_timestamp=1_700_000_000,
    )


# ─── Test case 1: clean win, single buyer ──────────────────────────────
def test_clean_win_single_buyer():
    sig = make_signal(direction="long", ref=100, target=102, stop=99)
    execs = [ExecutionRecord(buyer_addr="0xBUYER1", capital_usd=1000.0,
                             actual_fill_price=100.05, twap_at_execution=100.0,
                             gas_used=150000)]
    s = settle(make_inputs(sig, twap=102.5, executions=execs))

    assert s.outcome == Outcome.WIN
    assert s.pnl_bps_gross == 250                        # (102.5 - 100) / 100 * 10000
    assert s.distinct_buyers == 1
    assert not s.self_purchase_detected


# ─── Test case 2: target reached after stop (loss) ─────────────────────
def test_loss_stop_hit():
    sig = make_signal(direction="long", ref=100, target=102, stop=99)
    execs = [ExecutionRecord(buyer_addr="0xBUYER1", capital_usd=1000.0,
                             actual_fill_price=100.0, twap_at_execution=100.0,
                             gas_used=150000)]
    s = settle(make_inputs(sig, twap=98.5, executions=execs))

    assert s.outcome == Outcome.LOSS
    assert s.pnl_bps_gross == -150


# ─── Test case 3: no target, no stop (expired) ─────────────────────────
def test_expired_neither_hit():
    sig = make_signal(direction="long", ref=100, target=102, stop=99)
    execs = [ExecutionRecord(buyer_addr="0xBUYER1", capital_usd=1000.0,
                             actual_fill_price=100.0, twap_at_execution=100.0,
                             gas_used=150000)]
    s = settle(make_inputs(sig, twap=100.5, executions=execs))

    assert s.outcome == Outcome.EXPIRED
    assert s.pnl_bps_gross == 0
    assert s.pnl_bps_net == 0


# ─── Test case 4: self-purchase excluded ────────────────────────────────
def test_self_purchase_excluded():
    sig = make_signal(direction="long", ref=100, target=102, stop=99)
    execs = [
        ExecutionRecord(buyer_addr="0xPUBLISHER", capital_usd=5000.0,
                        actual_fill_price=100.0, twap_at_execution=100.0, gas_used=150000),
        ExecutionRecord(buyer_addr="0xBUYER1", capital_usd=1000.0,
                        actual_fill_price=100.0, twap_at_execution=100.0, gas_used=150000),
    ]
    s = settle(make_inputs(sig, twap=102.5, executions=execs, publisher_addr="0xPUBLISHER"))

    assert s.self_purchase_detected
    assert s.distinct_buyers == 1                # publisher excluded
    assert s.capital_deployed_usd == 1000.0      # publisher's $5000 excluded


# ─── Test case 5: short direction ───────────────────────────────────────
def test_short_win():
    sig = make_signal(direction="short", ref=100, target=98, stop=101)
    execs = [ExecutionRecord(buyer_addr="0xBUYER1", capital_usd=1000.0,
                             actual_fill_price=100.0, twap_at_execution=100.0,
                             gas_used=150000)]
    s = settle(make_inputs(sig, twap=97.5, executions=execs))

    assert s.outcome == Outcome.WIN
    assert s.pnl_bps_gross == 250                # short profits when price drops


# ─── Reputation update tests ───────────────────────────────────────────
def test_reputation_update_muted_no_buyers():
    sig = make_signal()
    s = settle(make_inputs(sig, twap=102.5, executions=[]))
    delta, weight = reputation_update(s, is_cold_start=False)
    assert delta == 0 and weight == 0


def test_reputation_update_muted_self_purchase_only():
    sig = make_signal()
    execs = [ExecutionRecord(buyer_addr="0xPUBLISHER", capital_usd=1000.0,
                             actual_fill_price=100.0, twap_at_execution=100.0, gas_used=150000)]
    s = settle(make_inputs(sig, twap=102.5, executions=execs, publisher_addr="0xPUBLISHER"))
    delta, _ = reputation_update(s, is_cold_start=False)
    assert delta == 0


def test_reputation_update_cold_start_half_weight():
    sig = make_signal()
    execs = [
        ExecutionRecord(buyer_addr="0xBUYER1", capital_usd=1000.0,
                        actual_fill_price=100.0, twap_at_execution=100.0, gas_used=150000),
        ExecutionRecord(buyer_addr="0xBUYER2", capital_usd=1000.0,
                        actual_fill_price=100.0, twap_at_execution=100.0, gas_used=150000),
    ]
    s = settle(make_inputs(sig, twap=102.5, executions=execs))

    _, weight_normal = reputation_update(s, is_cold_start=False)
    _, weight_cold = reputation_update(s, is_cold_start=True)
    assert weight_cold <= weight_normal // 2 + 1  # cold-start halves weight (allow rounding)


if __name__ == "__main__":
    # Allow running without pytest installed
    import sys
    fail = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ✓ {name}")
            except AssertionError as e:
                print(f"  ✗ {name}: {e}")
                fail += 1
    sys.exit(1 if fail else 0)
