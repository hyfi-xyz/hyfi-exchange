// SPDX-License-Identifier: BUSL-1.1
pragma solidity 0.8.36;

import {Script, console2} from "forge-std/Script.sol";
import {HyFi} from "../../../src/HyFi.sol";
import {Utils} from "../../../test/Utils.sol";

/// @notice Sets the withdrawer role on the HyFi hook. Must be broadcast by the owner's key.
contract SetWithdrawer is Script, Utils {
    // ------------------------------------------------------------------
    // Inputs - edit these before running
    // ------------------------------------------------------------------

    address public newWithdrawer = address(0);

    // ------------------------------------------------------------------

    function run() external {
        require(newWithdrawer != address(0), "SetWithdrawer: set newWithdrawer before running");

        uint chainId = block.chainid;
        HyFi hyfi = getHyFi(chainId);

        uint privateKey = vm.envUint("PRIVATE_KEY_HYFI_DEPLOYER");
        address sender = vm.addr(privateKey);

        console2.log("=== Setting HyFi Withdrawer ===");
        console2.log("chainId:", chainId);
        console2.log("hook:", address(hyfi));
        console2.log("owner:", hyfi.owner());
        console2.log("sender:", sender);
        console2.log("current withdrawer:", hyfi.withdrawer());
        console2.log("new withdrawer:", newWithdrawer);

        require(sender == hyfi.owner(), "SetWithdrawer: sender is not the owner");

        vm.startBroadcast(privateKey);
        hyfi.setWithdrawer(newWithdrawer);
        vm.stopBroadcast();

        // ------------------------------------------------------------------
        // Verify
        // ------------------------------------------------------------------
        console2.log("\n=== Verification ===");
        console2.log("withdrawer:", hyfi.withdrawer());
        require(hyfi.withdrawer() == newWithdrawer, "SetWithdrawer: withdrawer not set");
        console2.log("Withdrawer set!");
    }
}
