"""
Validator algorithm tests — v2.

Covers the path-aware multi-checkpoint TWAP outcome resolver and the
WIN_PARTIAL / INCONCLUSIVE additions to the Outcome enum.

The legacy v1 single-TWAP test_short_win has been removed because v2 is
long-only at the schema layer.
"""
try:
    import pytest  # noqa: F401
except ImportError:
    pass

from agents.shared.signal_schema import EntryCondition, Outcome, Signal
from agents.validator.algorithm import (
    Checkpoint,
    ExecutionRecord,
    SettlementInputs,
    reputation_update,
    settle,
)


def make_signal(ref=100.0, target=102.0, stop=99.0, horizon=3600, metadata=None):
    return Signal(
        signal_id="0x" + "ab" * 32,
        publisher="swing.sibylfi.eth",
        token="eip155:84532/erc20:0xWETH",
        direction="long",
        entry_condition=EntryCondition(type="market_at_publication", reference_price=ref),
        target_price=target,
        stop_price=stop,
        horizon_seconds=horizon,
        confidence_bps=6500,
        published_at_block=12345678,
        metadata=metadata,
        signature="0x" + "00" * 65,
    )


def cps(*pairs: tuple[float, int]) -> list[Checkpoint]:
    """cps((100.0, 0), (101.0, 1800), ...) → list[Checkpoint]"""
    return [Checkpoint(price=p, t=t) for (p, t) in pairs]


def make_inputs(
    signal,
    *,
    checkpoints,
    executions=None,
    publisher_addr="0xPUBLISHER",
):
    return SettlementInputs(
        signal=signal,
        publisher_addr=publisher_addr,
        checkpoints=checkpoints,
        executions=executions or [],
        eth_usd_at_horizon=3450.0,
        base_sepolia_gas_price_wei=1_000_000_000,
        settled_at_block=12_345_900,
        settled_at_timestamp=1_700_000_000,
    )


# ─── WIN: target hit before stop ────────────────────────────────────────
def test_win_target_before_stop():
    sig = make_signal(ref=100, target=102, stop=99)
    execs = [ExecutionRecord(buyer_addr="0xBUYER1", capital_usd=1000.0,
                             actual_fill_price=100.05, twap_at_execution=100.0,
                             gas_used=150000)]
    s = settle(make_inputs(sig, checkpoints=cps(
        (100.0, 0),
        (101.0, 900),
        (102.5, 1800),    # target hits here
        (101.0, 2700),
        (102.5, 3600),
    ), executions=execs))

    assert s.outcome == Outcome.WIN
    assert s.pnl_bps_gross == 250
    assert s.distinct_buyers == 1


# ─── WIN_PARTIAL: TP1 then stop, both within horizon ────────────────────
def test_win_partial_tp1_then_stop():
    sig = make_signal(ref=100, target=103, stop=99, metadata={"tp1": 101.5})
    execs = [
        ExecutionRecord(buyer_addr="0xBUYER1", capital_usd=1000.0,
                        actual_fill_price=100.0, twap_at_execution=100.0, gas_used=150000),
        ExecutionRecord(buyer_addr="0xBUYER2", capital_usd=1000.0,
                        actual_fill_price=100.0, twap_at_execution=100.0, gas_used=150000),
    ]
    s = settle(make_inputs(sig, checkpoints=cps(
        (100.0, 0),
        (101.7, 900),    # TP1 (101.5) hits here
        (100.5, 1800),
        (98.5, 2700),    # stop (99) hits here
        (98.0, 3600),
    ), executions=execs))

    assert s.outcome == Outcome.WIN_PARTIAL
    # WIN_PARTIAL PnL is computed against TP1 (101.5), not horizon (98.0)
    assert s.pnl_bps_gross == 150     # (101.5 - 100) / 100 * 10000


# ─── LOSS: stop hit before target ───────────────────────────────────────
def test_loss_stop_before_target():
    sig = make_signal(ref=100, target=102, stop=99)
    execs = [ExecutionRecord(buyer_addr="0xBUYER1", capital_usd=1000.0,
                             actual_fill_price=100.0, twap_at_execution=100.0,
                             gas_used=150000)]
    s = settle(make_inputs(sig, checkpoints=cps(
        (100.0, 0),
        (99.5, 900),
        (98.5, 1800),    # stop hits here
        (102.5, 2700),   # target hits later, but stop already won
        (102.5, 3600),
    ), executions=execs))

    assert s.outcome == Outcome.LOSS


# ─── EXPIRED: neither target nor stop hit ────────────────────────────────
def test_expired_neither_hit():
    sig = make_signal(ref=100, target=102, stop=99)
    execs = [ExecutionRecord(buyer_addr="0xBUYER1", capital_usd=1000.0,
                             actual_fill_price=100.0, twap_at_execution=100.0,
                             gas_used=150000)]
    s = settle(make_inputs(sig, checkpoints=cps(
        (100.0, 0),
        (100.5, 900),
        (100.3, 1800),
        (100.7, 2700),
        (100.5, 3600),
    ), executions=execs))

    assert s.outcome == Outcome.EXPIRED
    assert s.pnl_bps_gross == 0
    assert s.pnl_bps_net == 0


# ─── INCONCLUSIVE: empty checkpoints (oracle gap) ──────────────────────
def test_inconclusive_on_empty_checkpoints():
    sig = make_signal(ref=100, target=102, stop=99)
    execs = [ExecutionRecord(buyer_addr="0xBUYER1", capital_usd=1000.0,
                             actual_fill_price=100.0, twap_at_execution=100.0,
                             gas_used=150000)]
    s = settle(make_inputs(sig, checkpoints=[], executions=execs))

    assert s.outcome == Outcome.INCONCLUSIVE
    assert s.pnl_bps_gross == 0


# ─── direction=long is asserted (defense-in-depth) ─────────────────────
def test_long_only_assertion():
    """settle() must reject any non-long direction even if it gets through somehow."""
    sig = make_signal(ref=100, target=102, stop=99)
    object.__setattr__(sig, "direction", "short")
    inp = make_inputs(sig, checkpoints=cps((100.0, 0), (102.5, 3600)))

    try:
        settle(inp)
        assert False, "settle() must assert direction == 'long'"
    except AssertionError as e:
        assert "long-only" in str(e)


# ─── Self-purchase exclusion still works with checkpoints ──────────────
def test_self_purchase_excluded_v2():
    sig = make_signal(ref=100, target=102, stop=99)
    execs = [
        ExecutionRecord(buyer_addr="0xPUBLISHER", capital_usd=5000.0,
                        actual_fill_price=100.0, twap_at_execution=100.0, gas_used=150000),
        ExecutionRecord(buyer_addr="0xBUYER1", capital_usd=1000.0,
                        actual_fill_price=100.0, twap_at_execution=100.0, gas_used=150000),
    ]
    s = settle(make_inputs(
        sig, checkpoints=cps((100.0, 0), (102.5, 3600)),
        executions=execs, publisher_addr="0xPUBLISHER",
    ))
    assert s.self_purchase_detected
    assert s.distinct_buyers == 1
    assert s.capital_deployed_usd == 1000.0


# ─── Reputation tests ──────────────────────────────────────────────────
def test_reputation_muted_no_buyers():
    sig = make_signal()
    s = settle(make_inputs(sig, checkpoints=cps((100.0, 0), (102.5, 3600)), executions=[]))
    delta, weight = reputation_update(s, is_cold_start=False)
    assert delta == 0 and weight == 0


def test_reputation_muted_inconclusive():
    """INCONCLUSIVE must short-circuit reputation updates (oracle gap, not agent's fault)."""
    sig = make_signal()
    execs = [
        ExecutionRecord(buyer_addr="0xBUYER1", capital_usd=1000.0,
                        actual_fill_price=100.0, twap_at_execution=100.0, gas_used=150000),
        ExecutionRecord(buyer_addr="0xBUYER2", capital_usd=1000.0,
                        actual_fill_price=100.0, twap_at_execution=100.0, gas_used=150000),
    ]
    s = settle(make_inputs(sig, checkpoints=[], executions=execs))
    delta, weight = reputation_update(s, is_cold_start=False)
    assert s.outcome == Outcome.INCONCLUSIVE
    assert delta == 0 and weight == 0


def test_reputation_win_partial_half_credit():
    """WIN_PARTIAL gets half the contribution a WIN of the same PnL would get."""
    sig_full = make_signal(ref=100, target=103, stop=99)
    sig_partial = make_signal(ref=100, target=103, stop=99, metadata={"tp1": 101.5})

    big_capital_execs = [
        ExecutionRecord(buyer_addr=f"0xBUYER{i}", capital_usd=10_000.0,
                        actual_fill_price=100.0, twap_at_execution=100.0, gas_used=150000)
        for i in range(2)
    ]

    s_win = settle(make_inputs(sig_full,
        checkpoints=cps((100.0, 0), (103.5, 1800), (104.0, 3600)),
        executions=big_capital_execs))
    assert s_win.outcome == Outcome.WIN

    s_partial = settle(make_inputs(sig_partial,
        checkpoints=cps((100.0, 0), (101.7, 900), (98.5, 2700), (98.0, 3600)),
        executions=big_capital_execs))
    assert s_partial.outcome == Outcome.WIN_PARTIAL

    delta_win, _ = reputation_update(s_win, is_cold_start=False)
    delta_partial, _ = reputation_update(s_partial, is_cold_start=False)

    # WIN_PARTIAL should give a positive delta but smaller than the WIN delta
    assert delta_win > 0
    assert 0 <= delta_partial <= delta_win


def test_reputation_cold_start_half_weight():
    sig = make_signal()
    execs = [
        ExecutionRecord(buyer_addr="0xBUYER1", capital_usd=1000.0,
                        actual_fill_price=100.0, twap_at_execution=100.0, gas_used=150000),
        ExecutionRecord(buyer_addr="0xBUYER2", capital_usd=1000.0,
                        actual_fill_price=100.0, twap_at_execution=100.0, gas_used=150000),
    ]
    s = settle(make_inputs(sig, checkpoints=cps((100.0, 0), (102.5, 3600)), executions=execs))
    _, weight_normal = reputation_update(s, is_cold_start=False)
    _, weight_cold = reputation_update(s, is_cold_start=True)
    assert weight_cold <= weight_normal // 2 + 1


if __name__ == "__main__":
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
