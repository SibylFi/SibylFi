// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * @title ValidatorSettle
 * @notice On-chain settlement record for SibylFi signals.
 *         The Validator Agent posts here after each signal's horizon expires.
 *         Reputation updates go to ERC-8004 ReputationRegistry on Sepolia
 *         via a separate transaction from the Validator wallet (no CCIP).
 *
 * @dev    Owned by the Validator wallet only. Read-public.
 *         Deployed on Base Sepolia.
 */
contract ValidatorSettle {
    // Outcomes
    enum Outcome {
        Pending,    // never set; default zero value
        Win,
        Loss,
        Expired
    }

    struct Settlement {
        address publisher;
        Outcome outcome;
        int256 pnlBps;       // signed; positive = win
        uint64 settledAt;    // block timestamp
        uint64 capitalWei;   // capital deployed on this signal, in wei equivalent
    }

    // State

    /// @notice Wallet authorized to post settlements. Set at deploy time.
    address public immutable validator;

    /// @notice Per-signal settlement record, keyed by signal_id.
    mapping(bytes32 => Settlement) public settlements;

    /// @notice Total signals settled (for indexing / pagination).
    uint256 public totalSettled;

    // Events

    event SignalSettled(
        bytes32 indexed signalId,
        address indexed publisher,
        Outcome outcome,
        int256 pnlBps,
        uint256 timestamp
    );

    // Errors

    error NotValidator();
    error AlreadySettled();
    error InvalidOutcome();

    // Modifiers

    modifier onlyValidator() {
        if (msg.sender != validator) revert NotValidator();
        _;
    }

    // Construction

    constructor(address _validator) {
        validator = _validator;
    }

    // Settlement

    /**
     * @notice Record the settlement of a signal.
     *         Called by the Validator Agent after horizon expiry.
     *         Reputation update on ERC-8004 is a separate tx from the same wallet.
     *
     * @param signalId  The signal_id from the publisher's signed payload (32 bytes).
     * @param publisher The Research Agent's address.
     * @param outcome   Win / Loss / Expired.
     * @param pnlBps    Net PnL in basis points (signed).
     * @param capitalWei Capital deployed by buyers, in wei-equivalent.
     */
    function settle(
        bytes32 signalId,
        address publisher,
        Outcome outcome,
        int256 pnlBps,
        uint64 capitalWei
    ) external onlyValidator {
        if (outcome == Outcome.Pending) revert InvalidOutcome();
        if (settlements[signalId].outcome != Outcome.Pending) revert AlreadySettled();

        settlements[signalId] = Settlement({
            publisher: publisher,
            outcome: outcome,
            pnlBps: pnlBps,
            settledAt: uint64(block.timestamp),
            capitalWei: capitalWei
        });
        totalSettled++;

        emit SignalSettled(signalId, publisher, outcome, pnlBps, block.timestamp);
    }

    // Views

    function getSettlement(bytes32 signalId) external view returns (Settlement memory) {
        return settlements[signalId];
    }

    function isSettled(bytes32 signalId) external view returns (bool) {
        return settlements[signalId].outcome != Outcome.Pending;
    }
}
