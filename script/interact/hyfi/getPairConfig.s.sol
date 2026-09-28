// SPDX-License-Identifier: BUSL-1.1
pragma solidity 0.8.36;

import {Script, console2} from "forge-std/Script.sol";
import {HyFi} from "../../../src/HyFi.sol";
import {Utils} from "../../../test/Utils.sol";
import {Addrs} from "../../Addrs.sol";
import {PoolKey} from "@uniswap/v4-core/src/types/PoolKey.sol";
import {PoolId} from "@uniswap/v4-core/src/types/PoolId.sol";

/// @notice Reads and logs a pair's HyFi configuration without changing it.
contract GetPairConfig is Script, Utils {
    /// @dev Token names, resolved through script/Addrs.sol for the current chain
    string public baseTokenName = "NVDAc";
    string public quoteTokenName = "USDC";

    function run() external view {
        uint chainId = block.chainid;
        HyFi hyfi = getHyFi(chainId);

        address baseToken = Addrs.get(chainId, baseTokenName);
        address quoteToken = Addrs.get(chainId, quoteTokenName);
        (PoolKey memory key,) = poolKeyFor(baseToken, quoteToken, address(hyfi));
        PoolId poolId = key.toId();
        (uint128 tickWidth, uint88 baseLiqUnit, uint24 feePerSecond, bool baseIsCurrency0) = hyfi.pairConfig(poolId);

        console2.log("=== HyFi Pair Config ===");
        console2.log("chainId:", chainId);
        console2.log("hook:", address(hyfi));
        console2.log("base:", baseTokenName, baseToken);
        console2.log("quote:", quoteTokenName, quoteToken);
        console2.log("poolId:");
        console2.logBytes32(PoolId.unwrap(poolId));
        console2.log("configured:", tickWidth != 0);
        console2.log("tickWidth: %e", tickWidth);
        console2.log("baseLiqUnit: %e", baseLiqUnit);
        console2.log("feePerSecond:", feePerSecond);
        console2.log("baseIsCurrency0:", baseIsCurrency0);
    }
}
