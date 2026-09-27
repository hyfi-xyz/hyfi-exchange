// SPDX-License-Identifier: UNLICENSED
pragma solidity 0.8.36;

import {Currency} from "@uniswap/v4-core/src/types/Currency.sol";
import {IHooks} from "@uniswap/v4-core/src/interfaces/IHooks.sol";
import {PoolKey} from "@uniswap/v4-core/src/types/PoolKey.sol";
import {PoolId, PoolIdLibrary} from "@uniswap/v4-core/src/types/PoolId.sol";
import {IV4Quoter} from "@uniswap/v4-periphery/src/interfaces/IV4Quoter.sol";
import {IQuoterV2} from "@uniswap/universal-router/lib/v3-periphery/contracts/interfaces/IQuoterV2.sol";

interface IHyFiBenchmark {
    function quoteDirect(PoolId poolId, bool zeroForOne, int amountSpecified)
        external
        view
        returns (uint amountIn, uint amountOut, uint stalenessFee, uint40 bookId);
}

/// @notice Quotes exact-input trades across venues in one eth_call and one block state.
/// @dev Deploy once per chain. No transactions are sent by batchQuote when called via eth_call.
contract BenchmarkQuoter {
    using PoolIdLibrary for PoolKey;

    enum PoolType {
        V3,
        V4,
        HYFI_DIRECT
    }

    struct PoolConfig {
        PoolType poolType;
        address t0;
        address t1;
        uint24 fee;
        int24 tickSpacing;
        address hooks;
        bytes hookData;
    }

    struct QuoteResult {
        uint amountOut;
        bool success;
        uint40 bookId;
        uint stalenessFee;
    }

    IV4Quoter public immutable v4Quoter;
    IQuoterV2 public immutable v3Quoter;

    constructor(address v4Quoter_, address v3Quoter_) {
        v4Quoter = IV4Quoter(v4Quoter_);
        v3Quoter = IQuoterV2(v3Quoter_);
    }

    /// @param pools Pool keys; t0/t1 must be sorted by address. For HyFi,
    /// fee/tickSpacing must match its configured pair, hooks=the HyFi address,
    /// and hookData is unused.
    /// @param amtsZeroToOne Exact input amounts of t0, shared by every pool.
    /// @param amtsOneToZero Exact input amounts of t1, shared by every pool.
    function batchQuote(PoolConfig[] calldata pools, uint[] calldata amtsZeroToOne, uint[] calldata amtsOneToZero)
        external
        returns (QuoteResult[][] memory outsZeroToOne, QuoteResult[][] memory outsOneToZero)
    {
        outsZeroToOne = new QuoteResult[][](pools.length);
        outsOneToZero = new QuoteResult[][](pools.length);
        for (uint i; i < pools.length; ++i) {
            outsZeroToOne[i] = new QuoteResult[](amtsZeroToOne.length);
            outsOneToZero[i] = new QuoteResult[](amtsOneToZero.length);
            for (uint j; j < amtsZeroToOne.length; ++j) {
                outsZeroToOne[i][j] = _quote(pools[i], true, amtsZeroToOne[j]);
            }
            for (uint j; j < amtsOneToZero.length; ++j) {
                outsOneToZero[i][j] = _quote(pools[i], false, amtsOneToZero[j]);
            }
        }
    }

    function _quote(PoolConfig calldata pool, bool zeroForOne, uint amountIn)
        internal
        returns (QuoteResult memory result)
    {
        if (amountIn == 0) return result;

        if (pool.poolType == PoolType.V3) {
            if (address(v3Quoter) == address(0)) return result;
            try v3Quoter.quoteExactInputSingle(
                IQuoterV2.QuoteExactInputSingleParams(
                    zeroForOne ? pool.t0 : pool.t1, zeroForOne ? pool.t1 : pool.t0, amountIn, pool.fee, 0
                )
            ) returns (uint amountOut, uint160, uint32, uint) {
                result = QuoteResult(amountOut, amountOut != 0, 0, 0);
            } catch {}
        } else if (pool.poolType == PoolType.V4) {
            if (address(v4Quoter) == address(0) || amountIn > type(uint128).max) return result;
            PoolKey memory key = _key(pool);
            try v4Quoter.quoteExactInputSingle(
                IV4Quoter.QuoteExactSingleParams(key, zeroForOne, uint128(amountIn), pool.hookData)
            ) returns (uint amountOut, uint) {
                result = QuoteResult(amountOut, amountOut != 0, 0, 0);
            } catch {}
        } else if (pool.poolType == PoolType.HYFI_DIRECT) {
            if (pool.hooks == address(0) || amountIn > uint(type(int).max)) return result;
            PoolId id = _key(pool).toId();
            int amountSpecified = -int(amountIn);
            try IHyFiBenchmark(pool.hooks).quoteDirect(id, zeroForOne, amountSpecified) returns (
                uint, uint amountOut, uint stalenessFee, uint40 bookId
            ) {
                result = QuoteResult(amountOut, amountOut != 0, bookId, stalenessFee);
            } catch {}
        }
    }

    function _key(PoolConfig calldata pool) internal pure returns (PoolKey memory) {
        return PoolKey(Currency.wrap(pool.t0), Currency.wrap(pool.t1), pool.fee, pool.tickSpacing, IHooks(pool.hooks));
    }
}
