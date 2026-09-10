// SPDX-License-Identifier: BUSL-1.1
pragma solidity 0.8.36;

import {Script, console2} from "forge-std/Script.sol";
import {HyFi} from "../../../src/HyFi.sol";
import {Utils} from "../../../test/Utils.sol";

/// @notice Initiates an ownership transfer of the HyFi hook. Because HyFi uses Ownable2Step,
/// the new owner must call `acceptOwnership()` in a separate transaction to complete the transfer.
/// Run this script with the current owner's key, then run acceptOwnership.s.sol with the new
/// owner's key.
contract TransferOwnership is Script, Utils {
    // ------------------------------------------------------------------
    // Inputs - edit these before running
    // ------------------------------------------------------------------

    /// @dev The address that will become the new owner after calling acceptOwnership()
    address public newOwner = 0xfb02922C96dBa9311db0780Faaef763d9700e6E1;

    // ------------------------------------------------------------------

    function run() external {
        require(newOwner != address(0), "TransferOwnership: set newOwner before running");

        uint chainId = block.chainid;
        HyFi hyfi = getHyFi(chainId);

        uint privateKey = vm.envUint("PRIVATE_KEY_HYFI_DEPLOYER");
        address sender = vm.addr(privateKey);

        console2.log("=== Transferring HyFi Ownership (Step 1/2) ===");
        console2.log("chainId:", chainId);
        console2.log("hook:", address(hyfi));
        console2.log("current owner:", hyfi.owner());
        console2.log("sender:", sender);
        console2.log("pending new owner:", newOwner);

        require(sender == hyfi.owner(), "TransferOwnership: sender is not the current owner");

        vm.startBroadcast(privateKey);
        hyfi.transferOwnership(newOwner);
        vm.stopBroadcast();

        // ------------------------------------------------------------------
        // Verify
        // ------------------------------------------------------------------
        console2.log("\n=== Verification ===");
        console2.log("pendingOwner:", hyfi.pendingOwner());
        require(hyfi.pendingOwner() == newOwner, "TransferOwnership: pendingOwner not set");
        console2.log("Step 1 complete. New owner must call acceptOwnership() to finalize.");
    }
}
