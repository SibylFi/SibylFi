// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ValidatorSettle} from "../src/ValidatorSettle.sol";

interface Vm {
    function envAddress(string calldata name) external view returns (address);
    function startBroadcast() external;
    function stopBroadcast() external;
}

contract DeployValidatorSettle {
    address private constant HEVM_ADDRESS = address(uint160(uint256(keccak256("hevm cheat code"))));
    Vm private constant vm = Vm(HEVM_ADDRESS);

    function run() external returns (ValidatorSettle) {
        address validator = vm.envAddress("VALIDATOR_WALLET");

        vm.startBroadcast();
        ValidatorSettle settle = new ValidatorSettle(validator);
        vm.stopBroadcast();

        return settle;
    }
}
