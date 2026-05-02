// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {SibylFiRegistrar} from "../src/SibylFiRegistrar.sol";

interface Vm {
    function envAddress(string calldata name) external view returns (address);
    function envUint(string calldata name) external view returns (uint256);
    function addr(uint256 privateKey) external pure returns (address);
    function startBroadcast(uint256 privateKey) external;
    function stopBroadcast() external;
}

/**
 * @title DeploySibylFiRegistrar
 * @notice Deploys SibylFiRegistrar.sol on Base Sepolia.
 *
 * Usage:
 *   forge script script/DeploySibylFiRegistrar.s.sol:DeploySibylFiRegistrar \
 *     --rpc-url $BASE_SEPOLIA_RPC \
 *     --broadcast --verify \
 *     --etherscan-api-key $BASESCAN_API_KEY
 *
 * Required env vars:
 *   DEPLOYER_KEY                 — private key of the deployer (becomes owner)
 *   L2_REGISTRY_ADDRESS          — deployed Durin L2Registry address on Base Sepolia
 *   ENSIP25_CHAIN_ID             — chain ID where ERC-8004 lives (11155111 for Sepolia)
 *   ENSIP25_REGISTRY_ADDRESS     — ERC-8004 IdentityRegistry address on Sepolia
 *
 * Post-deploy:
 *   1. Call L2Registry.addRegistrar(deployedAddress) from the parent-name owner wallet
 *   2. Copy address into contracts/deployed-addresses.json
 *   3. Export ABI: forge inspect SibylFiRegistrar abi --json > contracts/abi/SibylFiRegistrar.json
 *   4. Mint 5 test subnames using the register() function
 *   5. Commit: "contracts: deploy SibylFiRegistrar on Base Sepolia"
 */
contract DeploySibylFiRegistrar {
    address private constant HEVM_ADDRESS = address(uint160(uint256(keccak256("hevm cheat code"))));
    Vm private constant vm = Vm(HEVM_ADDRESS);

    function run() external returns (SibylFiRegistrar) {
        uint256 deployerKey = vm.envUint("DEPLOYER_KEY");
        address l2Registry = vm.envAddress("L2_REGISTRY_ADDRESS");
        uint256 ensip25ChainId = vm.envUint("ENSIP25_CHAIN_ID");
        address ensip25Registry = vm.envAddress("ENSIP25_REGISTRY_ADDRESS");

        vm.startBroadcast(deployerKey);
        SibylFiRegistrar registrar = new SibylFiRegistrar(
            l2Registry,
            ensip25ChainId,
            ensip25Registry
        );
        vm.stopBroadcast();

        return registrar;
    }
}
