// SPDX-License-Identifier: BUSL-1.1
pragma solidity 0.8.36;

/// @notice Maps chainId + contract/token name to its address on that chain, so tests and
/// scripts can resolve addresses from just a name and `block.chainid`. Kept dependency-free;
/// typed wrappers (getPm, getERC20, ...) live in test/Utils.sol where the interfaces are.
library Addrs {
    error UnknownAddress(uint chainId, string name);

    uint internal constant ROBINHOOD = 4663;
    uint internal constant BASE = 8453;
    uint internal constant ARBITRUM = 42161;

    function get(uint chainId, string memory name) internal pure returns (address) {
        bytes32 h = keccak256(bytes(name));
        if (chainId == ROBINHOOD) {
            if (h == keccak256("HyFi")) return 0x2AC29f18B22a12917D4653406B0D2Fe7B592A888;
            if (h == keccak256("PoolManager")) return 0x8366a39CC670B4001A1121B8F6A443A643e40951;
            if (h == keccak256("PositionManager")) return 0x58daec3116aae6D93017bAAea7749052E8a04fA7;
            if (h == keccak256("UniversalRouter")) return 0x8876789976dEcBfCbBbe364623C63652db8C0904;
            if (h == keccak256("Permit2")) return 0x000000000022D473030F116dDEE9F6B43aC78BA3;
            if (h == keccak256("NATIVE")) return address(0);
            if (h == keccak256("USDG")) return 0x5fc5360D0400a0Fd4f2af552ADD042D716F1d168;
            if (h == keccak256("NVDA")) return 0xd0601CE157Db5bdC3162BbaC2a2C8aF5320D9EEC;
            if (h == keccak256("QuoterV2")) return 0x33e885eD0Ec9bF04EcfB19341582aADCb4c8A9E7;
            if (h == keccak256("V4Quoter")) return 0x8Dc178eFB8111BB0973Dd9d722ebeFF267c98F94;
        }

        if (chainId == BASE) {
            if (h == keccak256("HyFi")) return 0xB23F731949145E158E656e1Abe128c5e617A6888;
            if (h == keccak256("PoolManager")) return 0x498581fF718922c3f8e6A244956aF099B2652b2b;
            if (h == keccak256("PositionManager")) return 0x7C5f5A4bBd8fD63184577525326123B519429bDc;
            if (h == keccak256("UniversalRouter")) return 0xFdf682F51FE81Aa4898F0AE2163d8A55c127fbC7;
            if (h == keccak256("Permit2")) return 0x000000000022D473030F116dDEE9F6B43aC78BA3;
            if (h == keccak256("NATIVE")) return address(0);
            if (h == keccak256("USDC")) return 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913;
            if (h == keccak256("NVDAc")) return 0xb20000000000000000000078ee7ce2fE4908108C;
            if (h == keccak256("QuoterV2")) return 0x3d4e44Eb1374240CE5F1B871ab261CD16335B76a;
            if (h == keccak256("V4Quoter")) return 0x0d5e0F971ED27FBfF6c2837bf31316121532048D;
        }

        if (chainId == ARBITRUM) {
            if (h == keccak256("HyFi")) return 0xc4f2bE5a31697DCBc7c7FAA0d6BDFaf2b57D2888;
            if (h == keccak256("PoolManager")) return 0x360E68faCcca8cA495c1B759Fd9EEe466db9FB32;
            if (h == keccak256("PositionManager")) return 0xd88F38F930b7952f2DB2432Cb002E7abbF3dD869;
            if (h == keccak256("UniversalRouter")) return 0x8B844f885672f333Bc0042cB669255f93a4C1E6b;
            if (h == keccak256("Permit2")) return 0x000000000022D473030F116dDEE9F6B43aC78BA3;
            if (h == keccak256("NATIVE")) return address(0);
            if (h == keccak256("USDC")) return 0xaf88d065e77c8cC2239327C5EDb3A432268e5831;
            if (h == keccak256("rSPCX")) return 0x5181b7Dd097B42d7787ee78Efab86f43D4E12f44;
            if (h == keccak256("QuoterV2")) return 0x61fFE014bA17989E743c5F6cB21bF9697530B21e;
            if (h == keccak256("V4Quoter")) return 0x3972C00f7ed4885e145823eb7C655375d275A1C5;
        }

        revert UnknownAddress(chainId, name);
    }

    function get(string memory name) internal view returns (address) {
        return get(block.chainid, name);
    }
}
