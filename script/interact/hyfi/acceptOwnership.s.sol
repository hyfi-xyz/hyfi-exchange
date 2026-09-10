// SPDX-License-Identifier: BUSL-1.1
pragma solidity 0.8.36;

import {Script, console2} from "forge-std/Script.sol";
import {HyFi} from "../../../src/HyFi.sol";
import {Utils} from "../../../test/Utils.sol";

contract AcceptOwnership is Script, Utils {
    function run() external {
        uint chainId = block.chainid;
        HyFi hyfi = getHyFi(chainId);

        uint privateKey = vm.envUint("PRIVATE_KEY_HYFI_DEPLOYER");
        address sender = vm.addr(privateKey);

        console2.log("=== Accepting HyFi Ownership (Step 2/2) ===");
        console2.log("chainId:", chainId);
        console2.log("hook:", address(hyfi));
        console2.log("current owner:", hyfi.owner());
        console2.log("pending owner:", hyfi.pendingOwner());
        console2.log("sender:", sender);

        require(sender == hyfi.pendingOwner(), "AcceptOwnership: sender is not the pending owner");

        vm.startBroadcast(privateKey);
        hyfi.acceptOwnership();
        vm.stopBroadcast();

        // ------------------------------------------------------------------
        // Verify
        // ------------------------------------------------------------------
        console2.log("\n=== Verification ===");
        console2.log("new owner:", hyfi.owner());
        require(hyfi.owner() == sender, "AcceptOwnership: ownership transfer failed");
        console2.log("Ownership transfer complete!");
    }
}
