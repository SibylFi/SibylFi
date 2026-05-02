// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {SibylFiRegistrar} from "../src/SibylFiRegistrar.sol";
import {IL2Registry} from "../src/interfaces/IL2Registry.sol";

// Mock del L2Registry de Durin para poder probar el Registrar localmente
contract MockL2Registry is IL2Registry {
    mapping(bytes32 => address) public _owners;
    mapping(bytes32 => mapping(string => string)) public texts;
    
    function baseNode() external pure returns (bytes32) {
        return keccak256("sibylfi.eth");
    }

    function createSubnode(
        bytes32 node,
        string calldata label,
        address ownerAddr,
        bytes[] calldata data
    ) external returns (bytes32) {
        _owners[node] = ownerAddr;
        return node;
    }

    function setAddr(bytes32 node, uint256 coinType, bytes memory a) external {
        // Mock simple
    }

    function setText(bytes32 node, string calldata key, string calldata value) external {
        texts[node][key] = value;
    }

    function makeNode(bytes32 parentNode, string calldata label) external pure returns (bytes32) {
        return keccak256(abi.encodePacked(parentNode, label));
    }

    function owner(bytes32 node) external view returns (address) {
        return _owners[node];
    }

    function addRegistrar(address registrar) external {
        // Mock simple
    }
}

interface Vm {
    function prank(address msgSender) external;
    function expectRevert(bytes4 revertData) external;
}

contract SibylFiRegistrarTest {
    address private constant HEVM_ADDRESS = address(uint160(uint256(keccak256("hevm cheat code"))));
    Vm private constant vm = Vm(HEVM_ADDRESS);

    SibylFiRegistrar public registrar;
    MockL2Registry public mockRegistry;
    
    address public owner = address(0x1);
    address public agentWallet = address(0x2);
    uint256 public agentId = 123;
    string public label = "alpha";
    
    // Config para ENSIP-25
    uint256 public constant CHAIN_ID = 11155111;
    address public constant REGISTRY_ADDR = 0x8004A169FB4a3325136EB29fA0ceB6D2e539a432;

    function setUp() public {
        mockRegistry = new MockL2Registry();
        // El constructor tiene 3 argumentos: registry, chainId, registryAddr
        // Usamos prank para que address(0x1) sea el dueño
        vm.prank(owner);
        registrar = new SibylFiRegistrar(address(mockRegistry), CHAIN_ID, REGISTRY_ADDR);
    }

    function test_register_flow() public {
        vm.prank(owner);
        registrar.register(label, agentWallet, agentId);

        bytes32 node = registrar.computeNode(label);
        
        // Verificar que se marcó como registrado
        require(registrar.registered(node), "Not marked as registered");
        
        // Verificar que el registro de texto ENSIP-25 se escribió correctamente
        // La dirección debe estar en minúsculas para que coincida con _addr2str
        string memory expectedKey = "agent-registration[11155111][0x8004a169fb4a3325136eb29fa0ceb6d2e539a432]";
        string memory val = mockRegistry.texts(node, expectedKey);
        
        require(keccak256(bytes(val)) == keccak256(bytes("123")), "ENSIP-25 value mismatch");
    }

    function test_revert_doubleRegistration() public {
        vm.prank(owner);
        registrar.register(label, agentWallet, agentId);

        vm.prank(owner);
        vm.expectRevert(bytes4(keccak256("LabelAlreadyRegistered()")));
        registrar.register(label, agentWallet, agentId);
    }

    function test_revert_notOwner() public {
        vm.prank(address(0xBAD));
        vm.expectRevert(bytes4(keccak256("NotOwner()")));
        registrar.register(label, agentWallet, agentId);
    }
}
