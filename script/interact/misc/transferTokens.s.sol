// SPDX-License-Identifier: BUSL-1.1
pragma solidity 0.8.36;

import {Script, console2} from "forge-std/Script.sol";
import {Utils} from "../../../test/Utils.sol";
import {IERC20Metadata} from "@openzeppelin/contracts/token/ERC20/extensions/IERC20Metadata.sol";

/// @notice Sends `amount` of a token (or native currency, tokenName = "NATIVE") from the sender's
/// own wallet to `recipient`. Not HyFi-specific - a general-purpose transfer for ops/funding tasks.
contract TransferTokens is Script, Utils {
    // ------------------------------------------------------------------
    // Inputs - edit these before running
    // ------------------------------------------------------------------

    string public tokenName = "NATIVE";
    uint public amount = 0;
    address public recipient = address(0);

    // ------------------------------------------------------------------

    function run() external {
        require(recipient != address(0), "TransferTokens: set recipient before running");

        uint chainId = block.chainid;
        bool isNative = keccak256(bytes(tokenName)) == keccak256("NATIVE");
        address token = isNative ? address(0) : address(getERC20(chainId, tokenName));

        uint privateKey = vm.envUint("PRIVATE_KEY_HYFI_DEPLOYER");
        address sender = vm.addr(privateKey);

        uint senderBalanceBefore = balanceOf(token, sender);
        uint recipientBalanceBefore = balanceOf(token, recipient);
        require(senderBalanceBefore >= amount, "TransferTokens: sender balance below amount");

        console2.log("=== Transferring tokens ===");
        console2.log("chainId:", chainId);
        console2.log("token:", token); // 0x0 = native currency
        console2.log("sender:", sender);
        console2.log("recipient:", recipient);
        console2.log("amount:", amount);

        vm.startBroadcast(privateKey);
        if (isNative) {
            (bool success,) = recipient.call{value: amount}("");
            require(success, "TransferTokens: native transfer failed");
        } else {
            IERC20Metadata(token).transfer(recipient, amount);
        }
        vm.stopBroadcast();

        // ------------------------------------------------------------------
        // Verify
        // ------------------------------------------------------------------
        console2.log("\n=== Verification ===");
        uint recipientBalanceAfter = balanceOf(token, recipient);
        require(recipientBalanceAfter == recipientBalanceBefore + amount, "TransferTokens: recipient balance did not increase by amount");
        console2.log("Recipient balance increased by:", amount);
        console2.log("Transfer completed successfully!");
    }
}
