// SPDX-License-Identifier: BUSL-1.1
pragma solidity 0.8.36;

import {Script, console2} from "forge-std/Script.sol";
import {HyFi} from "../../../src/HyFi.sol";
import {Utils} from "../../../test/Utils.sol";
import {Addrs} from "../../Addrs.sol";
import {PoolKey} from "@uniswap/v4-core/src/types/PoolKey.sol";
import {PoolId} from "@uniswap/v4-core/src/types/PoolId.sol";
import {IERC20Metadata} from "@openzeppelin/contracts/token/ERC20/extensions/IERC20Metadata.sol";

/// @notice Sets a pair's configuration on HyFi without initializing its Uniswap v4 pool.
contract SetPairConfig is Script, Utils {
    // ------------------------------------------------------------------
    // Inputs - edit these before running
    // ------------------------------------------------------------------

    /// @dev Token names, resolved through script/Addrs.sol for the current chain
    string public baseTokenName = "NVDAc";
    string public quoteTokenName = "USDC";

    /// @dev Nominal quote tokens per whole base token per tick, scaled by 1e18
    uint256 public tickQuotePerBaseX18 = 0.01e18;
    /// @dev Nominal base tokens represented by 1 unit of tick liquidity, scaled by 1e18
    uint256 public baseLiqUnitX18 = 0.5e18;
    /// @dev Staleness fee in pips (1e-6), charged per second since the book timestamp
    uint24 public feePerSecond = 50;

    // ------------------------------------------------------------------

    function run() external {
        uint chainId = block.chainid;
        HyFi hyfi = getHyFi(chainId);

        address baseToken = Addrs.get(chainId, baseTokenName);
        address quoteToken = Addrs.get(chainId, quoteTokenName);
        uint8 baseDecimals = baseToken == address(0) ? 18 : IERC20Metadata(baseToken).decimals();
        uint8 quoteDecimals = quoteToken == address(0) ? 18 : IERC20Metadata(quoteToken).decimals();
        uint256 tickQuoteWei = _toWei(tickQuotePerBaseX18, quoteDecimals);
        uint256 baseLiqUnitWei = _toWei(baseLiqUnitX18, baseDecimals);
        require(baseLiqUnitWei <= type(uint88).max, "SetPairConfig: baseLiqUnit too large");
        uint88 baseLiqUnit = uint88(baseLiqUnitWei);
        (PoolKey memory key, bool baseIsCurrency0) = poolKeyFor(baseToken, quoteToken, address(hyfi));
        uint128 tickWidth = calcTickWidth(tickQuoteWei, baseDecimals);

        console2.log("=== Configuring pair ===");
        console2.log("chainId:", chainId);
        console2.log("hook:", address(hyfi));
        console2.log("base:", baseTokenName, baseToken);
        console2.log("quote:", quoteTokenName, quoteToken);
        console2.log("baseDecimals:", baseDecimals);
        console2.log("quoteDecimals:", quoteDecimals);
        console2.log("baseIsCurrency0:", baseIsCurrency0);
        console2.log("tickQuoteWei: %e", tickQuoteWei);
        console2.log("tickWidth: %e", tickWidth);
        console2.log("baseLiqUnit: %e", baseLiqUnit);
        console2.log("feePerSecond:", feePerSecond);

        vm.startBroadcast(vm.envUint("PRIVATE_KEY_HYFI_DEPLOYER"));
        hyfi.setPairConfig(key, tickWidth, baseLiqUnit, feePerSecond, baseIsCurrency0);
        vm.stopBroadcast();

        // ------------------------------------------------------------------
        // Verify
        // ------------------------------------------------------------------
        console2.log("\n=== Verification ===");
        (uint128 setTickWidth, uint88 setBaseLiqUnit, uint24 setFeePerSecond, bool setBaseIsCurrency0) = hyfi.pairConfig(key.toId());
        require(setTickWidth == tickWidth, "SetPairConfig: tickWidth not set correctly");
        require(setBaseLiqUnit == baseLiqUnit, "SetPairConfig: baseLiqUnit not set correctly");
        require(setFeePerSecond == feePerSecond, "SetPairConfig: feePerSecond not set correctly");
        require(setBaseIsCurrency0 == baseIsCurrency0, "SetPairConfig: baseIsCurrency0 not set correctly");
        console2.log("Pair config verified on-chain");

        console2.log("\n=== Summary ===");
        console2.log("poolId:");
        console2.logBytes32(PoolId.unwrap(key.toId()));
        console2.log("Pair configured successfully!");
    }

    function _toWei(uint256 nominalX18, uint8 decimals) private pure returns (uint256) {
        uint256 scaled = nominalX18 * (10 ** uint256(decimals));
        require(scaled % 1e18 == 0, "SetPairConfig: nominal amount has too much precision");
        return scaled / 1e18;
    }
}
