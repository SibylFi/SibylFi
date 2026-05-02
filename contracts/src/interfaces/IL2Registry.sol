// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * @title IL2Registry
 * @notice Minimal interface for the Durin L2Registry (Namestone).
 *         Only the functions SibylFi needs are included.
 *         Source: https://github.com/namestonehq/durin/blob/main/src/interfaces/IL2Registry.sol
 */
interface IL2Registry {
    function baseNode() external view returns (bytes32);

    function createSubnode(
        bytes32 node,
        string calldata label,
        address owner,
        bytes[] calldata data
    ) external returns (bytes32);

    function setAddr(bytes32 node, uint256 coinType, bytes memory a) external;

    function setText(bytes32 node, string calldata key, string calldata value) external;

    function makeNode(
        bytes32 parentNode,
        string calldata label
    ) external pure returns (bytes32);

    function owner(bytes32 node) external view returns (address);

    function addRegistrar(address registrar) external;
}
