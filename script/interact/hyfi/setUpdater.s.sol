// SPDX-License-Identifier: BUSL-1.1
pragma solidity 0.8.36;

import {Script, console2} from "forge-std/Script.sol";
import {HyFi} from "../../../src/HyFi.sol";
import {Utils} from "../../../test/Utils.sol";

/// @notice Sets the updater role on the HyFi hook. Must be broadcast by the owner's key.
contract SetUpdater is Script, Utils {
    // ------------------------------------------------------------------
    // Inputs - edit these before running
    // ------------------------------------------------------------------

    address public newUpdater = address(0);

    // ------------------------------------------------------------------

    function run() external {
        require(newUpdater != address(0), "SetUpdater: set newUpdater before running");

        uint chainId = block.chainid;
        HyFi hyfi = getHyFi(chainId);

        uint privateKey = vm.envUint("PRIVATE_KEY_HYFI_DEPLOYER");
        address sender = vm.addr(privateKey);

        console2.log("=== Setting HyFi Updater ===");
        console2.log("chainId:", chainId);
        console2.log("hook:", address(hyfi));
        console2.log("owner:", hyfi.owner());
        console2.log("sender:", sender);
        console2.log("current updater:", hyfi.updater());
        console2.log("new updater:", newUpdater);

        require(sender == hyfi.owner(), "SetUpdater: sender is not the owner");

        vm.startBroadcast(privateKey);
        hyfi.setUpdater(newUpdater);
        vm.stopBroadcast();

        // ------------------------------------------------------------------
        // Verify
        // ------------------------------------------------------------------
        console2.log("\n=== Verification ===");
        console2.log("updater:", hyfi.updater());
        require(hyfi.updater() == newUpdater, "SetUpdater: updater not set");
        console2.log("Updater set!");
    }
}
