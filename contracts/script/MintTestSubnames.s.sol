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
 * @title MintTestSubnames
 * @notice Mints 5 fallback-demo ENS subnames immediately after SibylFiRegistrar deploy.
 *         These exist so judges can see verified ENSIP-25 records even if the
 *         live registration UI fails on demo day.
 *
 * Usage:
 *   forge script script/MintTestSubnames.s.sol:MintTestSubnames \
 *     --rpc-url $BASE_SEPOLIA_RPC \
 *     --broadcast
 *
 * Required env vars:
 *   DEPLOYER_KEY               — same key that owns the SibylFiRegistrar
 *   SIBYLFI_REGISTRAR_ADDRESS  — deployed SibylFiRegistrar address
 *   RESEARCH_MEANREV_ADDR      — Research Mean-Rev agent wallet
 *   RESEARCH_MOMENTUM_ADDR     — Research Momentum agent wallet
 *   RESEARCH_NEWS_ADDR         — Research News agent wallet
 *   RISK_ADDR                  — Risk Agent wallet
 *   VALIDATOR_ADDR             — Validator Agent wallet
 */
contract MintTestSubnames {
    address private constant HEVM_ADDRESS = address(uint160(uint256(keccak256("hevm cheat code"))));
    Vm private constant vm = Vm(HEVM_ADDRESS);

    function run() external {
        uint256 deployerKey = vm.envUint("DEPLOYER_KEY");
        address registrarAddr = vm.envAddress("SIBYLFI_REGISTRAR_ADDRESS");

        address meanrev  = vm.envAddress("RESEARCH_MEANREV_ADDR");
        address momentum = vm.envAddress("RESEARCH_MOMENTUM_ADDR");
        address news     = vm.envAddress("RESEARCH_NEWS_ADDR");
        address risk     = vm.envAddress("RISK_ADDR");
        address val      = vm.envAddress("VALIDATOR_ADDR");

        SibylFiRegistrar registrar = SibylFiRegistrar(registrarAddr);

        vm.startBroadcast(deployerKey);

        // Agent IDs are sequential starting from 1 (ERC-8004 minting order)
        registrar.register("reversal",  meanrev,  1);  // THE REVERSAL — mean-reversion
        registrar.register("wave",      momentum, 2);  // THE WAVE — momentum
        registrar.register("herald",    news,     3);  // THE HERALD — news-driven
        registrar.register("guardian",  risk,     4);  // THE GUARDIAN — risk agent
        registrar.register("oracle",    val,      5);  // THE ORACLE — validator

        vm.stopBroadcast();
    }
}
