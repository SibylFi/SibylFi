// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * @title ValidatorSettle
 * @notice On-chain settlement record for SibylFi signals.
 *         The Validator Agent updates this registry after each signal's horizon expires.
 *         Reputation metrics are maintained on the ERC-8004 ReputationRegistry.
 *
 * @dev    Owned by the Validator wallet. Deployed on Base Sepolia.
 *         Provides a transparent record of outcomes and evidence links to 0G Storage.
 */
contract ValidatorSettle {

    // Outcomes — matches specs/signal-validator.md Section 7

    enum Outcome {
        Pending,       // 0 — default zero value, never set explicitly
        Win,           // 1 — TWAP reached target before stop within horizon
        Loss,          // 2 — TWAP reached stop before target within horizon
        Expired,       // 3 — horizon ended, neither target nor stop reached
        Inconclusive,  // 4 — <80% TWAP checkpoints or oracle cardinality < 100
        Invalid        // 5 — reference_price mismatch > 0.1% (fraud)
    }

    // Settlement record

    struct Settlement {
        address publisher;      // Research Agent address
        Outcome outcome;        // settlement result
        int256  pnlBps;         // net PnL in basis points (signed; positive = win)
        uint64  settledAt;      // block.timestamp at settlement
        uint64  capitalWei;     // capital deployed on this signal, wei-equivalent
        bytes32 evidenceHash;   // keccak256 of the full settlement evidence stored in 0G Storage
    }

    // State

    /// @notice Wallet authorized to post settlements. Set at deploy time.
    address public immutable validator;

    /// @notice Per-signal settlement record, keyed by signal_id.
    mapping(bytes32 => Settlement) public settlements;

    /// @notice Total signals settled (for indexing / pagination).
    uint256 public totalSettled;

    /// @notice Ordered list of settled signal IDs (for enumeration).
    bytes32[] public settledSignalIds;

    // Events

    event SignalSettled(
        bytes32 indexed signalId,
        address indexed publisher,
        Outcome outcome,
        int256  pnlBps,
        uint256 timestamp
    );

    // Errors

    error NotValidator();
    error AlreadySettled();
    error InvalidOutcome();
    error ArrayLengthMismatch();

    // Modifiers

    modifier onlyValidator() {
        if (msg.sender != validator) revert NotValidator();
        _;
    }

    // Construction

    constructor(address _validator) {
        validator = _validator;
    }

    // Settlement — single

    /**
     * @notice Record the settlement of a single signal.
     * @param signalId     The signal_id from the publisher's signed payload (32 bytes).
     * @param publisher    The Research Agent's address.
     * @param outcome      Win / Loss / Expired / Inconclusive / Invalid.
     * @param pnlBps       Net PnL in basis points (signed).
     * @param capitalWei   Capital deployed by buyers, in wei-equivalent.
     * @param evidenceHash keccak256 of the full evidence payload stored in 0G Storage.
     */
    function settle(
        bytes32 signalId,
        address publisher,
        Outcome outcome,
        int256  pnlBps,
        uint64  capitalWei,
        bytes32 evidenceHash
    ) external onlyValidator {
        _settle(signalId, publisher, outcome, pnlBps, capitalWei, evidenceHash);
    }

    // Settlement — batch (for demo efficiency)

    /**
     * @notice Settle multiple signals in one transaction.
     *         Improves efficiency and reduces gas costs for high-volume settlement operations.
     * @dev    All arrays must have the same length. Reverts on first failure.
     */
    function settleBatch(
        bytes32[] calldata signalIds,
        address[] calldata publishers,
        Outcome[] calldata outcomes,
        int256[]  calldata pnlsBps,
        uint64[]  calldata capitalsWei,
        bytes32[] calldata evidenceHashes
    ) external onlyValidator {
        uint256 len = signalIds.length;
        if (
            publishers.length != len ||
            outcomes.length   != len ||
            pnlsBps.length    != len ||
            capitalsWei.length != len ||
            evidenceHashes.length != len
        ) revert ArrayLengthMismatch();

        for (uint256 i = 0; i < len; ) {
            _settle(
                signalIds[i],
                publishers[i],
                outcomes[i],
                pnlsBps[i],
                capitalsWei[i],
                evidenceHashes[i]
            );
            unchecked { ++i; }
        }
    }

    // Views

    function getSettlement(bytes32 signalId) external view returns (Settlement memory) {
        return settlements[signalId];
    }

    function isSettled(bytes32 signalId) external view returns (bool) {
        return settlements[signalId].outcome != Outcome.Pending;
    }

    /// @notice Return the total count of settled signals (for pagination).
    function getSettledCount() external view returns (uint256) {
        return settledSignalIds.length;
    }

    /// @notice Return a page of settled signal IDs for frontend enumeration.
    /// @param offset Start index (0-based).
    /// @param limit  Max number of IDs to return.
    function getSettledSignalIds(uint256 offset, uint256 limit)
        external view returns (bytes32[] memory)
    {
        uint256 total = settledSignalIds.length;
        if (offset >= total) {
            return new bytes32[](0);
        }
        uint256 end = offset + limit;
        if (end > total) end = total;
        uint256 size = end - offset;
        bytes32[] memory result = new bytes32[](size);
        for (uint256 i = 0; i < size; ) {
            result[i] = settledSignalIds[offset + i];
            unchecked { ++i; }
        }
        return result;
    }

    // Internal

    function _settle(
        bytes32 signalId,
        address publisher,
        Outcome outcome,
        int256  pnlBps,
        uint64  capitalWei,
        bytes32 evidenceHash
    ) internal {
        if (outcome == Outcome.Pending) revert InvalidOutcome();
        if (settlements[signalId].outcome != Outcome.Pending) revert AlreadySettled();

        settlements[signalId] = Settlement({
            publisher:    publisher,
            outcome:      outcome,
            pnlBps:       pnlBps,
            settledAt:    uint64(block.timestamp),
            capitalWei:   capitalWei,
            evidenceHash: evidenceHash
        });

        settledSignalIds.push(signalId);
        totalSettled++;

        emit SignalSettled(signalId, publisher, outcome, pnlBps, block.timestamp);
    }
}
