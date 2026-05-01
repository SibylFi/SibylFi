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

    function test_initialState() public view {
        require(settle.validator() == validator, "validator mismatch");
        require(settle.totalSettled() == 0, "unexpected settled count");
        require(!settle.isSettled(sigId), "signal starts settled");
    }

    function test_settle_storesAndEmits() public {
        vm.expectEmit(true, true, false, true);
        emit SignalSettled(
            sigId,
            publisher,
            ValidatorSettle.Outcome.Win,
            218,
            block.timestamp
        );

        vm.prank(validator);
        settle.settle(sigId, publisher, ValidatorSettle.Outcome.Win, 218, 1_000_000);

        require(settle.isSettled(sigId), "signal not settled");
        require(settle.totalSettled() == 1, "settled count mismatch");

        ValidatorSettle.Settlement memory s = settle.getSettlement(sigId);
        require(s.publisher == publisher, "publisher mismatch");
        require(s.outcome == ValidatorSettle.Outcome.Win, "outcome mismatch");
        require(s.pnlBps == 218, "pnl mismatch");
        require(s.capitalWei == 1_000_000, "capital mismatch");
    }

    function test_settle_loss_negativePnl() public {
        vm.prank(validator);
        settle.settle(sigId, publisher, ValidatorSettle.Outcome.Loss, -127, 500_000);

        ValidatorSettle.Settlement memory s = settle.getSettlement(sigId);
        require(s.pnlBps == -127, "pnl mismatch");
        require(s.outcome == ValidatorSettle.Outcome.Loss, "outcome mismatch");
    }

    function test_settle_revertsWhen_notValidator() public {
        vm.prank(outsider);
        vm.expectRevert(ValidatorSettle.NotValidator.selector);
        settle.settle(sigId, publisher, ValidatorSettle.Outcome.Win, 100, 1000);
    }

    function test_settle_revertsWhen_alreadySettled() public {
        vm.startPrank(validator);
        settle.settle(sigId, publisher, ValidatorSettle.Outcome.Win, 100, 1000);

        vm.expectRevert(ValidatorSettle.AlreadySettled.selector);
        settle.settle(sigId, publisher, ValidatorSettle.Outcome.Loss, -50, 1000);
        vm.stopPrank();
    }

    function test_settle_revertsWhen_pendingOutcome() public {
        vm.prank(validator);
        vm.expectRevert(ValidatorSettle.InvalidOutcome.selector);
        settle.settle(sigId, publisher, ValidatorSettle.Outcome.Pending, 0, 0);
    }
}
