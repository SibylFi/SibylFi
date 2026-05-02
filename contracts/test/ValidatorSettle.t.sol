// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ValidatorSettle} from "../src/ValidatorSettle.sol";

interface Vm {
    function expectEmit(bool checkTopic1, bool checkTopic2, bool checkTopic3, bool checkData) external;
    function expectRevert(bytes4 revertData) external;
    function prank(address msgSender) external;
    function startPrank(address msgSender) external;
    function stopPrank() external;
}

contract ValidatorSettleTest {
    address private constant HEVM_ADDRESS = address(uint160(uint256(keccak256("hevm cheat code"))));
    Vm private constant vm = Vm(HEVM_ADDRESS);

    ValidatorSettle public settle;

    address public validator = address(uint160(0xA11CE));
    address public outsider = address(uint160(0xBAD));
    address public publisher = address(uint160(0x9F4A));

    bytes32 public sigId = keccak256("signal-1");
    bytes32 public sigId2 = keccak256("signal-2");
    bytes32 public sigId3 = keccak256("signal-3");
    bytes32 public evidenceHash = keccak256("evidence-payload-1");

    event SignalSettled(
        bytes32 indexed signalId,
        address indexed publisher,
        ValidatorSettle.Outcome outcome,
        int256 pnlBps,
        uint256 timestamp
    );

    function setUp() public {
        settle = new ValidatorSettle(validator);
    }

    // ── Initial state ──────────────────────────────────────────────

    function test_initialState() public view {
        require(settle.validator() == validator, "validator mismatch");
        require(settle.totalSettled() == 0, "unexpected settled count");
        require(settle.getSettledCount() == 0, "unexpected settledSignalIds count");
        require(!settle.isSettled(sigId), "signal starts settled");
    }

    // ── Single settle: Win ─────────────────────────────────────────

    function test_settle_win_storesAndEmits() public {
        vm.expectEmit(true, true, false, true);
        emit SignalSettled(
            sigId,
            publisher,
            ValidatorSettle.Outcome.Win,
            218,
            block.timestamp
        );

        vm.prank(validator);
        settle.settle(sigId, publisher, ValidatorSettle.Outcome.Win, 218, 1_000_000, evidenceHash);

        require(settle.isSettled(sigId), "signal not settled");
        require(settle.totalSettled() == 1, "settled count mismatch");
        require(settle.getSettledCount() == 1, "settledSignalIds count mismatch");

        ValidatorSettle.Settlement memory s = settle.getSettlement(sigId);
        require(s.publisher == publisher, "publisher mismatch");
        require(s.outcome == ValidatorSettle.Outcome.Win, "outcome mismatch");
        require(s.pnlBps == 218, "pnl mismatch");
        require(s.capitalWei == 1_000_000, "capital mismatch");
        require(s.evidenceHash == evidenceHash, "evidence hash mismatch");
    }

    // ── Single settle: Loss with negative PnL ──────────────────────

    function test_settle_loss_negativePnl() public {
        vm.prank(validator);
        settle.settle(sigId, publisher, ValidatorSettle.Outcome.Loss, -127, 500_000, evidenceHash);

        ValidatorSettle.Settlement memory s = settle.getSettlement(sigId);
        require(s.pnlBps == -127, "pnl mismatch");
        require(s.outcome == ValidatorSettle.Outcome.Loss, "outcome mismatch");
    }

    // ── Single settle: Expired ─────────────────────────────────────

    function test_settle_expired() public {
        vm.prank(validator);
        settle.settle(sigId, publisher, ValidatorSettle.Outcome.Expired, 15, 300_000, evidenceHash);

        ValidatorSettle.Settlement memory s = settle.getSettlement(sigId);
        require(s.outcome == ValidatorSettle.Outcome.Expired, "outcome mismatch");
        require(s.pnlBps == 15, "expired pnl should be small positive");
    }

    // ── Single settle: Inconclusive (oracle issue) ─────────────────

    function test_settle_inconclusive() public {
        vm.prank(validator);
        settle.settle(sigId, publisher, ValidatorSettle.Outcome.Inconclusive, 0, 0, bytes32(0));

        ValidatorSettle.Settlement memory s = settle.getSettlement(sigId);
        require(s.outcome == ValidatorSettle.Outcome.Inconclusive, "outcome mismatch");
        require(s.pnlBps == 0, "inconclusive pnl should be 0");
    }

    // ── Single settle: Invalid (fraud) ─────────────────────────────

    function test_settle_invalid_fraud() public {
        vm.prank(validator);
        settle.settle(sigId, publisher, ValidatorSettle.Outcome.Invalid, -300, 0, evidenceHash);

        ValidatorSettle.Settlement memory s = settle.getSettlement(sigId);
        require(s.outcome == ValidatorSettle.Outcome.Invalid, "outcome mismatch");
        require(s.pnlBps == -300, "invalid should carry -300 penalty");
    }

    // ── Revert: not validator ──────────────────────────────────────

    function test_settle_revertsWhen_notValidator() public {
        vm.prank(outsider);
        vm.expectRevert(ValidatorSettle.NotValidator.selector);
        settle.settle(sigId, publisher, ValidatorSettle.Outcome.Win, 100, 1000, evidenceHash);
    }

    // ── Revert: already settled ────────────────────────────────────

    function test_settle_revertsWhen_alreadySettled() public {
        vm.startPrank(validator);
        settle.settle(sigId, publisher, ValidatorSettle.Outcome.Win, 100, 1000, evidenceHash);

        vm.expectRevert(ValidatorSettle.AlreadySettled.selector);
        settle.settle(sigId, publisher, ValidatorSettle.Outcome.Loss, -50, 1000, evidenceHash);
        vm.stopPrank();
    }

    // ── Revert: pending outcome ────────────────────────────────────

    function test_settle_revertsWhen_pendingOutcome() public {
        vm.prank(validator);
        vm.expectRevert(ValidatorSettle.InvalidOutcome.selector);
        settle.settle(sigId, publisher, ValidatorSettle.Outcome.Pending, 0, 0, bytes32(0));
    }

    // ── Batch settlement ───────────────────────────────────────────

    function test_settleBatch_multipleSignals() public {
        bytes32[] memory ids = new bytes32[](3);
        ids[0] = sigId;
        ids[1] = sigId2;
        ids[2] = sigId3;

        address[] memory pubs = new address[](3);
        pubs[0] = publisher;
        pubs[1] = publisher;
        pubs[2] = publisher;

        ValidatorSettle.Outcome[] memory outcomes = new ValidatorSettle.Outcome[](3);
        outcomes[0] = ValidatorSettle.Outcome.Win;
        outcomes[1] = ValidatorSettle.Outcome.Loss;
        outcomes[2] = ValidatorSettle.Outcome.Expired;

        int256[] memory pnls = new int256[](3);
        pnls[0] = 200;
        pnls[1] = -150;
        pnls[2] = 10;

        uint64[] memory caps = new uint64[](3);
        caps[0] = 1_000_000;
        caps[1] = 500_000;
        caps[2] = 250_000;

        bytes32[] memory hashes = new bytes32[](3);
        hashes[0] = keccak256("ev-1");
        hashes[1] = keccak256("ev-2");
        hashes[2] = keccak256("ev-3");

        vm.prank(validator);
        settle.settleBatch(ids, pubs, outcomes, pnls, caps, hashes);

        require(settle.totalSettled() == 3, "batch: total mismatch");
        require(settle.getSettledCount() == 3, "batch: ids count mismatch");
        require(settle.isSettled(sigId), "batch: sig1 not settled");
        require(settle.isSettled(sigId2), "batch: sig2 not settled");
        require(settle.isSettled(sigId3), "batch: sig3 not settled");

        // Verify individual records
        ValidatorSettle.Settlement memory s1 = settle.getSettlement(sigId);
        require(s1.outcome == ValidatorSettle.Outcome.Win, "batch: s1 outcome");
        require(s1.pnlBps == 200, "batch: s1 pnl");

        ValidatorSettle.Settlement memory s2 = settle.getSettlement(sigId2);
        require(s2.outcome == ValidatorSettle.Outcome.Loss, "batch: s2 outcome");
        require(s2.pnlBps == -150, "batch: s2 pnl");
    }

    // ── Batch revert: array mismatch ───────────────────────────────

    function test_settleBatch_revertsWhen_arrayMismatch() public {
        bytes32[] memory ids = new bytes32[](2);
        ids[0] = sigId;
        ids[1] = sigId2;

        address[] memory pubs = new address[](1); // mismatch!
        pubs[0] = publisher;

        ValidatorSettle.Outcome[] memory outcomes = new ValidatorSettle.Outcome[](2);
        outcomes[0] = ValidatorSettle.Outcome.Win;
        outcomes[1] = ValidatorSettle.Outcome.Loss;

        int256[] memory pnls = new int256[](2);
        pnls[0] = 100;
        pnls[1] = -100;

        uint64[] memory caps = new uint64[](2);
        caps[0] = 1000;
        caps[1] = 1000;

        bytes32[] memory hashes = new bytes32[](2);
        hashes[0] = bytes32(0);
        hashes[1] = bytes32(0);

        vm.prank(validator);
        vm.expectRevert(ValidatorSettle.ArrayLengthMismatch.selector);
        settle.settleBatch(ids, pubs, outcomes, pnls, caps, hashes);
    }

    // ── Pagination view ────────────────────────────────────────────

    function test_getSettledSignalIds_pagination() public {
        // Settle 3 signals
        vm.startPrank(validator);
        settle.settle(sigId, publisher, ValidatorSettle.Outcome.Win, 100, 1000, evidenceHash);
        settle.settle(sigId2, publisher, ValidatorSettle.Outcome.Loss, -50, 500, evidenceHash);
        settle.settle(sigId3, publisher, ValidatorSettle.Outcome.Expired, 5, 200, evidenceHash);
        vm.stopPrank();

        // Full page
        bytes32[] memory all = settle.getSettledSignalIds(0, 10);
        require(all.length == 3, "page: expected 3");
        require(all[0] == sigId, "page: first signal");

        // Partial page
        bytes32[] memory page = settle.getSettledSignalIds(1, 1);
        require(page.length == 1, "page: expected 1");
        require(page[0] == sigId2, "page: second signal");

        // Out of range
        bytes32[] memory empty = settle.getSettledSignalIds(10, 5);
        require(empty.length == 0, "page: expected empty");
    }
}
