// SPDX-License-Identifier: UNLICENSED
pragma solidity 0.8.36;

import {HyFiSetup} from "./HyFiSetup.sol";
import {HyFi} from "../src/HyFi.sol";
import {Currency} from "@uniswap/v4-core/src/types/Currency.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";

/// @dev Zero-amount trades are rejected. Without the `ZeroAmount` guard the walk kernels would be
/// entered with `remaining == 0`, skip the loop entirely and still persist `amountLeft = 0` over a
/// partially-consumed tick - making `_avail` treat that tick as untouched and refilling it at the
/// same price. Repeating {partial fill, zero-amount trade} would then fill unbounded size at the
/// tip. The Uniswap path is unaffected (the PoolManager rejects amountSpecified == 0), so these
/// tests exercise the direct path and the quote view.
contract HyFiHookZeroAmountTest is HyFiSetup {
    function _tokens(Pair memory p, bool sellingBase) internal pure returns (address tIn, address tOut) {
        (tIn, tOut) = sellingBase
            ? (Currency.unwrap(p.base), Currency.unwrap(p.quote))
            : (Currency.unwrap(p.quote), Currency.unwrap(p.base));
    }

    // ------------------------------------------------------------------
    // Rejection
    // ------------------------------------------------------------------

    function test_zeroAmount_RevertWhen_swapExactInDirect() public {
        (address tIn, address tOut) = _tokens(nvdaPair, false);
        vm.prank(trader);
        vm.expectRevert(HyFi.ZeroAmount.selector);
        hyfi.swapExactInDirect(tIn, tOut, 0, trader);
    }

    function test_zeroAmount_RevertWhen_swapExactOutDirect() public {
        (address tIn, address tOut) = _tokens(nvdaPair, false);
        vm.prank(trader);
        vm.expectRevert(HyFi.ZeroAmount.selector);
        hyfi.swapExactOutDirect(tIn, tOut, 0, trader);
    }

    function test_zeroAmount_RevertWhen_sellingBase() public {
        (address tIn, address tOut) = _tokens(nvdaPair, true);
        vm.prank(trader);
        vm.expectRevert(HyFi.ZeroAmount.selector);
        hyfi.swapExactInDirect(tIn, tOut, 0, trader);
    }

    function test_zeroAmount_RevertWhen_nativeInput() public {
        (address tIn, address tOut) = _tokens(ethPair, true);
        vm.prank(trader);
        vm.expectRevert(HyFi.ZeroAmount.selector);
        hyfi.swapExactInDirect{value: 0}(tIn, tOut, 0, trader);
    }

    function test_zeroAmount_RevertWhen_quoteDirect() public {
        vm.expectRevert(HyFi.ZeroAmount.selector);
        hyfi.quoteDirect(nvdaPair.id, false, 0);
    }

    /// @dev PairNotConfigured is checked before the amount, so an unconfigured pair still reports
    /// the more specific error.
    function test_zeroAmount_RevertWhen_pairNotConfigured() public {
        vm.prank(trader);
        vm.expectRevert(HyFi.PairNotConfigured.selector);
        hyfi.swapExactInDirect(address(toka), address(nvda), 0, trader);
    }

    // ------------------------------------------------------------------
    // The book pointer survives a rejected zero-amount trade
    // ------------------------------------------------------------------

    /// @dev Consolidated from the zero-swap PoCs: partially consume the tip tick, attempt the
    /// zero-amount trade, and assert the walk pointer is untouched.
    function test_zeroAmount_doesNotResetWalkPointer() public {
        (address tIn, address tOut) = _tokens(nvdaPair, false);

        swapExactOutDirectAs(hyfi, trader, tIn, tOut, 0.05e18, trader, 100e6);
        (,,, uint8 curBefore,, uint96 leftBefore,) = hyfi.getBookSide(nvdaPair.id, false);
        assertEq(curBefore, 0, "tip tick partially consumed");
        assertGt(leftBefore, 0, "amountLeft recorded");

        vm.prank(trader);
        vm.expectRevert(HyFi.ZeroAmount.selector);
        hyfi.swapExactInDirect(tIn, tOut, 0, trader);

        (,,, uint8 curAfter,, uint96 leftAfter,) = hyfi.getBookSide(nvdaPair.id, false);
        assertEq(curAfter, curBefore, "curTick unchanged");
        assertEq(leftAfter, leftBefore, "amountLeft preserved - tick not resurrected");
    }

    /// @dev The exploit loop: without the guard each iteration refilled the tip tick, so the
    /// trader could buy the book's entire tip capacity over and over at the tip price. With the
    /// guard the second round prices strictly worse (it walks into deeper ticks) and the book
    /// eventually reverts InsufficientLiquidity rather than filling forever.
    function test_zeroAmount_cannotRefillTipTickInALoop() public {
        (address tIn, address tOut) = _tokens(nvdaPair, false);
        // Ask side holds 2+3+1 = 6 units * 0.1 NVDA = 0.6 NVDA
        uint tipCapacity = 2 * uint(nvdaPair.baseLiqUnit);

        (uint firstIn,) = swapExactOutDirectAs(hyfi, trader, tIn, tOut, tipCapacity, trader, 1_000e6);
        (,,, uint8 cur,, uint96 left,) = hyfi.getBookSide(nvdaPair.id, false);
        assertEq(cur, 1, "tip tick fully consumed, pointer advanced");
        assertEq(left, 0, "no partial remainder");

        vm.prank(trader);
        vm.expectRevert(HyFi.ZeroAmount.selector);
        hyfi.swapExactInDirect(tIn, tOut, 0, trader);

        // Same size again now fills from tick 1 onwards, at a strictly worse (higher) price
        (uint secondIn,) = swapExactOutDirectAs(hyfi, trader, tIn, tOut, tipCapacity, trader, 1_000e6);
        assertGt(secondIn, firstIn, "second fill priced deeper in the book, not at the tip");

        // Only 6 units existed; the 7th unit is past endTick
        vm.startPrank(trader);
        IERC20(tIn).approve(address(hyfi), 1_000e6);
        vm.expectRevert(HyFi.InsufficientLiquidity.selector);
        hyfi.swapExactOutDirect(tIn, tOut, 3 * uint(nvdaPair.baseLiqUnit), trader);
        vm.stopPrank();
    }

    /// @dev The partially-consumed tick keeps its exact remaining capacity across a rejected
    /// zero-amount trade: draining the remainder costs the same as it would have beforehand.
    function test_zeroAmount_partialTickRemainderIsPreserved() public {
        (address tIn, address tOut) = _tokens(tokPair, true);
        uint tickCap = 2 * uint(tokPair.baseLiqUnit);

        swapExactInDirectAs(hyfi, trader, tIn, tOut, tickCap - 1, trader);
        (,,, uint8 cur,, uint96 left,) = hyfi.getBookSide(tokPair.id, true);
        assertEq(cur, 0, "still on tick 0");
        assertEq(left, 1, "1 wei of tick 0 left");

        vm.prank(trader);
        vm.expectRevert(HyFi.ZeroAmount.selector);
        hyfi.swapExactOutDirect(tIn, tOut, 0, trader);

        (,,, cur,, left,) = hyfi.getBookSide(tokPair.id, true);
        assertEq(cur, 0, "still on tick 0 after rejected trade");
        assertEq(left, 1, "remainder intact");

        // Consuming that last wei advances to tick 1 exactly as it would have without the attempt
        swapExactInDirectAs(hyfi, trader, tIn, tOut, 1, trader);
        (,,, cur,, left,) = hyfi.getBookSide(tokPair.id, true);
        assertEq(cur, 1, "advanced to tick 1");
        assertEq(left, 0, "no remainder carried over");
    }

    /// @dev The hook can never pay out more base than the ask book advertised.
    function test_zeroAmount_bookCannotOverfill() public {
        (address tIn, address tOut) = _tokens(nvdaPair, false);
        uint bookCapacity = 6 * uint(nvdaPair.baseLiqUnit);
        uint traderBefore = IERC20(tOut).balanceOf(trader);

        swapExactOutDirectAs(hyfi, trader, tIn, tOut, bookCapacity, trader, 10_000e6);

        vm.startPrank(trader);
        IERC20(tIn).approve(address(hyfi), 10_000e6);
        vm.expectRevert(HyFi.ZeroAmount.selector);
        hyfi.swapExactInDirect(tIn, tOut, 0, trader);
        vm.expectRevert(HyFi.InsufficientLiquidity.selector);
        hyfi.swapExactOutDirect(tIn, tOut, 1, trader);
        vm.stopPrank();

        assertEq(IERC20(tOut).balanceOf(trader) - traderBefore, bookCapacity, "filled exactly the advertised book");
    }
}
