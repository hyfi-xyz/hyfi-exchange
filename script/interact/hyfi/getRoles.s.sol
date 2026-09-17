// SPDX-License-Identifier: BUSL-1.1
pragma solidity 0.8.36;

import {Script, console2} from "forge-std/Script.sol";
import {HyFi} from "../../../src/HyFi.sol";
import {Utils} from "../../../test/Utils.sol";

/// @notice Reads and logs HyFi's current owner, updater and withdrawer. Read-only - no
/// broadcast needed.
contract GetRoles is Script, Utils {
    function run() external view {
        uint chainId = block.chainid;
        HyFi hyfi = getHyFi(chainId);

        console2.log("=== HyFi Roles ===");
        console2.log("chainId:", chainId);
        console2.log("hook:", address(hyfi));
        console2.log("owner:", hyfi.owner());
        console2.log("pendingOwner:", hyfi.pendingOwner());
        console2.log("updater:", hyfi.updater());
        console2.log("withdrawer:", hyfi.withdrawer());
    }
}
