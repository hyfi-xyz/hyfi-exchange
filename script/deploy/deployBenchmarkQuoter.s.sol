// SPDX-License-Identifier: UNLICENSED
pragma solidity 0.8.36;

import {Script, console2} from "forge-std/Script.sol";
import {Addrs} from "../Addrs.sol";
import {BenchmarkQuoter} from "../../src/misc/BenchmarkQuoter.sol";

contract DeployBenchmarkQuoter is Script {
    function run() external {
        address v4Quoter = Addrs.get("V4Quoter");
        address v3Quoter = Addrs.get("QuoterV2");
        vm.startBroadcast(vm.envUint("PRIVATE_KEY_HYFI_DEPLOYER"));
        BenchmarkQuoter benchmark = new BenchmarkQuoter(v4Quoter, v3Quoter);
        console2.log("Uniswap V4 Quoter:", v4Quoter);
        console2.log("Uniswap V3 QuoterV2:", v3Quoter);
        vm.stopBroadcast();
        console2.log("BenchmarkQuoter:", address(benchmark));
    }
}
