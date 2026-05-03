// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {SibylFiRegistrar} from "../src/SibylFiRegistrar.sol";

interface Vm {
    function envAddress(string calldata name) external view returns (address);
    function envUint(string calldata name) external view returns (uint256);
    function startBroadcast(uint256 privateKey) external;
    function stopBroadcast() external;
}

/**
 * @title RegisterMainAgents
 * @notice Registers the two main demo agents (Scalper and Swing) on Base Sepolia.
 */
contract RegisterMainAgents {
    address private constant HEVM_ADDRESS = address(uint160(uint256(keccak256("hevm cheat code"))));
    Vm private constant vm = Vm(HEVM_ADDRESS);

    function run() external {
        uint256 deployerKey = vm.envUint("DEPLOYER_KEY");
        address registrarAddr = vm.envAddress("SIBYLFI_REGISTRAR_ADDRESS");

        // Wallets
        address scalperWallet = vm.envAddress("RESEARCH_MOMENTUM_ADDR"); // We'll map Momentum to Scalper
        address swingWallet   = vm.envAddress("RESEARCH_MEANREV_ADDR");  // We'll map Mean-Rev to Swing

        SibylFiRegistrar registrar = SibylFiRegistrar(registrarAddr);

        vm.startBroadcast(deployerKey);

        // Register Scalper (ID 6)
        registrar.register("scalper", scalperWallet, 6);
        
        // Register Swing (ID 7)
        registrar.register("swing", swingWallet, 7);

        vm.stopBroadcast();
    }
}
