// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IL2Registry} from "./interfaces/IL2Registry.sol";

/**
 * @title SibylFiRegistrar
 * @notice SibylFi's ENS Durin L2 Registrar for Base Sepolia.
 *         Wraps the upstream Durin L2Registry to register agent subnames
 *         (e.g. "reversal.sibylfi.eth") and write ENSIP-25 text records that
 *         link each subname to its ERC-8004 agent ID on Sepolia.
 *
 * @dev    Deployed on Base Sepolia. Access control is enforced to ensure 
 *         that only authorized entities can register subnames under the 
 *         parent identity.
 */
contract SibylFiRegistrar {

    // State

    /// @notice The Durin L2Registry on Base Sepolia.
    IL2Registry public immutable registry;

    /// @notice Owner of this registrar (can register new subnames).
    address public owner;

    /// @notice The chain ID where the ENSIP-25 registry (ERC-8004) lives.
    ///         For SibylFi: 11155111 (Sepolia).
    uint256 public immutable ensip25ChainId;

    /// @notice The ERC-8004 IdentityRegistry address on Sepolia.
    ///         Used to construct the ENSIP-25 text record key.
    address public immutable ensip25RegistryAddress;

    /// @notice ENSIP-11 coinType for the deployment chain.
    uint256 public immutable coinType;

    /// @notice Track registered labels to prevent double-registration.
    mapping(bytes32 => bool) public registered;

    /// @notice Ordered list of registered labels for enumeration.
    string[] public registeredLabels;

    // Events

    event SubnameRegistered(
        string  indexed label,
        address indexed owner,
        uint256 agentId,
        bytes32 node
    );

    event OwnershipTransferred(address indexed previousOwner, address indexed newOwner);

    // Errors

    error NotOwner();
    error LabelAlreadyRegistered();
    error EmptyLabel();

    // Modifiers

    modifier onlyOwner() {
        if (msg.sender != owner) revert NotOwner();
        _;
    }

    // Construction

    /**
     * @param _registry             Address of the deployed Durin L2Registry.
     * @param _ensip25ChainId       Chain ID where ERC-8004 lives (11155111 for Sepolia).
     * @param _ensip25RegistryAddr  ERC-8004 IdentityRegistry address on that chain.
     */
    constructor(
        address _registry,
        uint256 _ensip25ChainId,
        address _ensip25RegistryAddr
    ) {
        registry = IL2Registry(_registry);
        ensip25ChainId = _ensip25ChainId;
        ensip25RegistryAddress = _ensip25RegistryAddr;
        owner = msg.sender;

        // ENSIP-11 coinType derivation
        uint256 chainId;
        assembly { chainId := chainid() }
        coinType = 0x80000000 | chainId;
    }

    // Registration

    /**
     * @notice Register a new ENS subname and write its ENSIP-25 text record.
     *
     * @param label      The subname label (e.g. "reversal" for "reversal.sibylfi.eth").
     * @param agentOwner The wallet address that will own this subname.
     * @param agentId    The ERC-8004 agent ID on Sepolia to link via ENSIP-25.
     *
     * @dev After calling this, the subname will have:
     *      - Forward resolution to agentOwner on this L2 chain
     *      - Forward resolution to agentOwner on mainnet (coinType 60)
     *      - ENSIP-25 text record: agent-registration[chainId][registryAddr] = agentId
     */
    /**
     * @notice Computes the ENS node (namehash) for a given label under the base node.
     */
    function computeNode(string calldata label) public view returns (bytes32) {
        return registry.makeNode(registry.baseNode(), label);
    }

    function register(
        string calldata label,
        address agentOwner,
        uint256 agentId
    ) external onlyOwner {
        if (bytes(label).length == 0) revert EmptyLabel();

        bytes32 node = computeNode(label);
        if (registered[node]) revert LabelAlreadyRegistered();

        // 1. Create the subnode in the L2Registry
        registry.createSubnode(
            registry.baseNode(),
            label,
            agentOwner,
            new bytes[](0)
        );

        // 2. Set forward resolution for this L2 chain (ENSIP-11)
        registry.setAddr(node, coinType, abi.encodePacked(agentOwner));

        // 3. Set forward resolution for mainnet ETH (coinType 60) for debugging
        registry.setAddr(node, 60, abi.encodePacked(agentOwner));

        // 4. Write ENSIP-25 text record linking to ERC-8004
        //    Key format: agent-registration[<chainId>][<registryAddress>]
        //    Value: the agent ID as a string
        string memory ensip25Key = string(
            abi.encodePacked(
                "agent-registration[",
                _uint2str(ensip25ChainId),
                "][",
                _addr2str(ensip25RegistryAddress),
                "]"
            )
        );
        registry.setText(node, ensip25Key, _uint2str(agentId));

        // 5. Track registration
        registered[node] = true;
        registeredLabels.push(label);

        emit SubnameRegistered(label, agentOwner, agentId, node);
    }

    // Views

    function getRegisteredCount() external view returns (uint256) {
        return registeredLabels.length;
    }

    // Admin

    function transferOwnership(address newOwner) external onlyOwner {
        emit OwnershipTransferred(owner, newOwner);
        owner = newOwner;
    }

    // Internal helpers

    /// @dev Convert uint to decimal string.
    function _uint2str(uint256 value) internal pure returns (string memory) {
        if (value == 0) return "0";
        uint256 tmp = value;
        uint256 digits;
        while (tmp != 0) { digits++; tmp /= 10; }
        bytes memory buf = new bytes(digits);
        while (value != 0) {
            digits--;
            buf[digits] = bytes1(uint8(48 + (value % 10)));
            value /= 10;
        }
        return string(buf);
    }

    /// @dev Convert address to checksummed hex string (lowercase for simplicity).
    function _addr2str(address a) internal pure returns (string memory) {
        bytes memory s = new bytes(42);
        s[0] = "0";
        s[1] = "x";
        for (uint256 i = 0; i < 20; i++) {
            uint8 b = uint8(uint160(a) >> (8 * (19 - i)));
            s[2 + i * 2] = _hexChar(b >> 4);
            s[3 + i * 2] = _hexChar(b & 0x0f);
        }
        return string(s);
    }

    function _hexChar(uint8 nibble) internal pure returns (bytes1) {
        return nibble < 10
            ? bytes1(nibble + 48)   // '0'-'9'
            : bytes1(nibble + 87);  // 'a'-'f'
    }
}
