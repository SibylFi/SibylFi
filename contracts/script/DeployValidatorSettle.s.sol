// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ValidatorSettle} from "../src/ValidatorSettle.sol";

interface Vm {
    function envAddress(string calldata name) external view returns (address);
    function envUint(string calldata name) external view returns (uint256);
    function addr(uint256 privateKey) external pure returns (address);
    function startBroadcast(uint256 privateKey) external;
    function stopBroadcast() external;
}

/**
 * @title DeployValidatorSettle
 * @notice Deploys ValidatorSettle.sol on Base Sepolia.
 *
 * Usage:
 *   forge script script/DeployValidatorSettle.s.sol:DeployValidatorSettle \
 *     --rpc-url $BASE_SEPOLIA_RPC \
 *     --broadcast --verify \
 *     --etherscan-api-key $BASESCAN_API_KEY
 *
 * Required env vars:
 *   VALIDATOR_KEY   — private key of the Validator wallet
 *
 * Post-deploy:
 *   1. Copy the deployed address into contracts/deployed-addresses.json
 *   2. Export ABI: forge inspect ValidatorSettle abi --json > contracts/abi/ValidatorSettle.json
 *   3. Verify on Basescan that source is visible
 *   4. Commit: "contracts: deploy ValidatorSettle v2 on Base Sepolia"
 */
contract DeployValidatorSettle {
    address private constant HEVM_ADDRESS = address(uint160(uint256(keccak256("hevm cheat code"))));
    Vm private constant vm = Vm(HEVM_ADDRESS);

    function run() external returns (ValidatorSettle) {
        uint256 deployerKey = vm.envUint("VALIDATOR_KEY");
        address validatorAddr = vm.addr(deployerKey);

        vm.startBroadcast(deployerKey);
        ValidatorSettle settle = new ValidatorSettle(validatorAddr);
        vm.stopBroadcast();

        return settle;
    }
}
