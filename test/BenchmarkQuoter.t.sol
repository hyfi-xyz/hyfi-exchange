// SPDX-License-Identifier: UNLICENSED
pragma solidity 0.8.36;

import {Test} from "forge-std/Test.sol";
import {BenchmarkQuoter} from "../src/misc/BenchmarkQuoter.sol";
import {PoolId} from "@uniswap/v4-core/src/types/PoolId.sol";
import {IV4Quoter} from "@uniswap/v4-periphery/src/interfaces/IV4Quoter.sol";
import {IQuoterV2} from "@uniswap/universal-router/lib/v3-periphery/contracts/interfaces/IQuoterV2.sol";

contract BenchmarkMockHyFi {
    function quoteDirect(PoolId, bool zeroForOne, int amountSpecified)
        external
        pure
        returns (uint, uint, uint, uint40)
    {
        uint amountIn = uint(-amountSpecified);
        require(amountIn <= 1000, "no liquidity");
        return (amountIn, amountIn * (zeroForOne ? 2 : 3), 7, 42);
    }

}

contract BenchmarkMockV3 {
    function quoteExactInputSingle(IQuoterV2.QuoteExactInputSingleParams memory params)
        external
        pure
        returns (uint, uint160, uint32, uint)
    {
        require(params.tokenIn != params.tokenOut, "same token");
        return (params.amountIn * 4, 0, 0, 0);
    }
}

contract BenchmarkMockV4 {
    function quoteExactInputSingle(IV4Quoter.QuoteExactSingleParams memory params)
        external
        pure
        returns (uint, uint)
    {
        return (uint(params.exactAmount) * (params.zeroForOne ? 5 : 6), 0);
    }
}

contract BenchmarkQuoterTest is Test {
    BenchmarkQuoter internal benchmark;
    BenchmarkMockHyFi internal hyfi;

    function setUp() public {
        hyfi = new BenchmarkMockHyFi();
        benchmark = new BenchmarkQuoter(address(new BenchmarkMockV4()), address(new BenchmarkMockV3()));
    }

    function _pool(BenchmarkQuoter.PoolType poolType, address hooks)
        internal
        pure
        returns (BenchmarkQuoter.PoolConfig memory)
    {
        return BenchmarkQuoter.PoolConfig(poolType, address(0x100), address(0x200), 0, 1, hooks, "");
    }

    function test_batchQuotesBothDirectionsAndKeepsFailuresPerPool() public {
        BenchmarkQuoter.PoolConfig[] memory pools = new BenchmarkQuoter.PoolConfig[](3);
        pools[0] = _pool(BenchmarkQuoter.PoolType.V3, address(0));
        pools[1] = _pool(BenchmarkQuoter.PoolType.V4, address(0));
        pools[2] = _pool(BenchmarkQuoter.PoolType.HYFI_DIRECT, address(hyfi));
        uint[] memory amounts0to1 = new uint[](2);
        amounts0to1[0] = 100;
        amounts0to1[1] = 1200;
        uint[] memory amounts1to0 = new uint[](1);
        amounts1to0[0] = 200;

        (BenchmarkQuoter.QuoteResult[][] memory forward, BenchmarkQuoter.QuoteResult[][] memory reverse) =
            benchmark.batchQuote(pools, amounts0to1, amounts1to0);

        assertEq(forward[0][0].amountOut, 400);
        assertEq(forward[1][0].amountOut, 500);
        assertEq(forward[2][0].amountOut, 200);
        assertEq(forward[2][0].bookId, 42);
        assertEq(forward[2][0].stalenessFee, 7);
        assertFalse(forward[2][1].success);
        assertTrue(forward[0][1].success);
        assertEq(reverse[1][0].amountOut, 1200);
        assertEq(reverse[2][0].amountOut, 600);
    }

    function test_v4OversizedAmountFailsOnlyItsQuote() public {
        BenchmarkQuoter.PoolConfig[] memory pools = new BenchmarkQuoter.PoolConfig[](2);
        pools[0] = _pool(BenchmarkQuoter.PoolType.V3, address(0));
        pools[1] = _pool(BenchmarkQuoter.PoolType.V4, address(0));
        uint[] memory amounts = new uint[](1);
        amounts[0] = uint(type(uint128).max) + 1;
        uint[] memory none = new uint[](0);

        (BenchmarkQuoter.QuoteResult[][] memory results,) = benchmark.batchQuote(pools, amounts, none);
        assertTrue(results[0][0].success);
        assertFalse(results[1][0].success);
    }
}
