#!/usr/bin/env python3
"""Sample indicative $100, $1,000, and $10,000 buy/sell quotes for HyFi and v3/v4.
All quotes use one pinned block per sample and are appended to CSV for price analysis.

Example:
    python script/python/benchmark/benchmark.py --chain base --pair NVDAc-USDC --once

Omit --once to keep sampling every 10 seconds. Token multipliers are checked
every 12 hours. Use --help for options.
"""

import argparse
import csv
import json
import os
import re
import sys
import time
from decimal import Decimal, ROUND_FLOOR
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ABIs.benchmark_quoter_abi import BENCHMARK_QUOTER_ABI  # noqa: E402
from ABIs.erc20_abi import ERC20_ABI  # noqa: E402
from config import CHAINS  # noqa: E402
from price_sources import PRICE_SOURCES  # noqa: E402


NATIVE = "0x0000000000000000000000000000000000000000"
USD_AMOUNTS = (100, 1000, 10000)
MULTIPLIER_CHECK_INTERVAL_S = 12 * 60 * 60
POOL_TYPES = {"v3": 0, "v4": 1, "hyfi_direct": 2}
CSV_HEADERS = [
    "sample_id", "observed_at", "block", "block_timestamp", "chain_id", "pair",
    "base_token", "quote_token", "reference_base_usd", "reference_quote_usd",
    "base_multiplier", "quote_multiplier",
    "notional_usd", "pool", "pool_type", "direction", "input_raw", "output_raw",
    "ok", "price_quote_per_base", "book_id", "staleness_fee_raw",
]


class MultiplierChangedError(RuntimeError):
    pass


def address(value):
    if not Web3.is_address(value):
        raise ValueError(f"Invalid token or contract address: {value}")
    return Web3.to_checksum_address(value)


def positive_decimal(value, label):
    result = Decimal(str(value))
    if not result.is_finite() or result <= 0:
        raise ValueError(f"{label} must be a positive finite number")
    return result


def reference_prices(pair_config, benchmark_config):
    """Return USD per underlying base and quote token from the updater's price source."""
    source = PRICE_SOURCES[pair_config["price_source"]]
    bid, ask, _ = source.get_top_of_book(pair_config)
    quote_usd = positive_decimal(benchmark_config.get("quote_usd", "1"), "benchmark.quote_usd")
    base_usd = positive_decimal((bid + ask) / 2, "reference base/quote price") * quote_usd
    return base_usd, quote_usd


def get_token_multiplier(w3, token_config, token_address, block_number):
    """Apply the same 1e18-scaled RWA token multiplier as the book updater."""
    fn_name = token_config.get("multiplier_fn")
    if not fn_name:
        return Decimal(1)
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", fn_name):
        raise ValueError("multiplier_fn must be a function name")
    abi = [{"type": "function", "name": fn_name, "stateMutability": "view",
            "inputs": [], "outputs": [{"name": "", "type": "uint256"}]}]
    contract = w3.eth.contract(address=token_address, abi=abi)
    raw = getattr(contract.functions, fn_name)().call(block_identifier=block_number)
    return positive_decimal(Decimal(raw) / Decimal(10**18), "token multiplier")


def build_amounts(base_usd, quote_usd, base_decimals, quote_decimals):
    base = [int((Decimal(usd) * 10**base_decimals / base_usd).to_integral_value(rounding=ROUND_FLOOR))
            for usd in USD_AMOUNTS]
    quote = [int((Decimal(usd) * 10**quote_decimals / quote_usd).to_integral_value(rounding=ROUND_FLOOR))
             for usd in USD_AMOUNTS]
    if min(base + quote) <= 0:
        raise ValueError("A USD size rounds to zero token units")
    return base, quote


def prepare_pools(benchmark_config, pair_config, hyfi_address, base, quote):
    """All pools share exact token addresses, so their raw outputs are comparable."""
    t0, t1 = sorted((base, quote), key=lambda token: int(token, 16))
    names = set()
    pools = []
    for entry in benchmark_config["pools"]:
        if entry.get("enabled", True) is False:
            continue
        name, kind = entry["name"], entry["type"]
        if name in names:
            raise ValueError(f"Duplicate pool name: {name}")
        if kind not in POOL_TYPES:
            raise ValueError(f"Unknown pool type for {name}: {kind}")
        names.add(name)
        if kind == "hyfi_direct":
            if any(key in entry for key in ("fee", "tick_spacing", "hooks")):
                raise ValueError(f"{name}: HyFi PoolKey comes from the shared pair config")
            fee = int(pair_config.get("fee", 0))
            tick_spacing = int(pair_config.get("tick_spacing", 1))
            hooks = address(hyfi_address)
        else:
            fee = int(entry.get("fee", 0))
            tick_spacing = int(entry.get("tick_spacing", 0))
            hooks = address(entry.get("hooks", NATIVE))
        hook_data = entry.get("hook_data", "0x")
        if not re.fullmatch(r"0x(?:[0-9a-fA-F]{2})*", hook_data):
            raise ValueError(f"Invalid hook_data for {name}")
        if kind == "hyfi_direct" and (tick_spacing <= 0 or hooks == NATIVE):
            raise ValueError(f"{name}: HyFi requires a positive tick spacing and hook address")
        if kind == "v3" and (t0 == NATIVE or t1 == NATIVE):
            raise ValueError(f"{name}: v3 requires ERC20 addresses; native ETH is not WETH")
        if kind == "v4" and tick_spacing <= 0:
            raise ValueError(f"{name}: v4 requires a positive tick_spacing")
        if not 0 <= fee < 2**24 or not -(2**23) <= tick_spacing < 2**23:
            raise ValueError(f"Fee or tick spacing out of range for {name}")
        pools.append((entry, (POOL_TYPES[kind], t0, t1, fee, tick_spacing, hooks, bytes.fromhex(hook_data[2:]))))
    if not pools:
        raise ValueError("No enabled pools")
    hyfi_hooks = [pool[5] for entry, pool in pools if entry["type"] == "hyfi_direct"]
    if len(hyfi_hooks) != 1:
        raise ValueError("Enable exactly one hyfi_direct pool")
    if any(entry["type"] == "v4" and pool[5] == hyfi_hooks[0] for entry, pool in pools):
        raise ValueError("Quote the HyFi hook with hyfi_direct, not the v4 quoter")
    return pools


def price_quote_per_base(direction, amount_in, amount_out, base_decimals, quote_decimals):
    if amount_out == 0:
        return ""
    if direction == "sell":
        price = (Decimal(amount_out) / 10**quote_decimals) / (Decimal(amount_in) / 10**base_decimals)
    else:
        price = (Decimal(amount_in) / 10**quote_decimals) / (Decimal(amount_out) / 10**base_decimals)
    return str(price)


def sample(contract, block, chain_id, pair_name, pools, base, quote,
           base_decimals, quote_decimals, base_usd, quote_usd,
           base_multiplier=Decimal(1), quote_multiplier=Decimal(1)):
    base_amts, quote_amts = build_amounts(base_usd, quote_usd, base_decimals, quote_decimals)
    base_is_t0 = int(base, 16) < int(quote, 16)
    amounts_0to1, amounts_1to0 = (base_amts, quote_amts) if base_is_t0 else (quote_amts, base_amts)
    out_0to1, out_1to0 = contract.functions.batchQuote(
        [pool for _, pool in pools], amounts_0to1, amounts_1to0
    ).call(block_identifier=block.number)
    observed_ns = time.time_ns()
    observed = datetime.fromtimestamp(observed_ns / 1e9, timezone.utc).isoformat(timespec="seconds")
    sample_id = f"{chain_id}-{block.number}-{observed_ns}"
    rows = []
    for i, (pool_config, _) in enumerate(pools):
        for j, usd in enumerate(USD_AMOUNTS):
            for direction in ("sell", "buy"):
                selling = direction == "sell"
                result = (out_0to1 if selling == base_is_t0 else out_1to0)[i][j]
                amount_in = (base_amts if selling else quote_amts)[j]
                amount_out, ok, book_id, fee = result
                rows.append({
                    "sample_id": sample_id,
                    "observed_at": observed,
                    "block": block.number,
                    "block_timestamp": block.timestamp,
                    "chain_id": chain_id,
                    "pair": pair_name,
                    "base_token": base,
                    "quote_token": quote,
                    "reference_base_usd": str(base_usd),
                    "reference_quote_usd": str(quote_usd),
                    "base_multiplier": str(base_multiplier),
                    "quote_multiplier": str(quote_multiplier),
                    "notional_usd": usd,
                    "pool": pool_config["name"],
                    "pool_type": pool_config["type"],
                    "direction": direction,
                    "input_raw": amount_in,
                    "output_raw": amount_out if ok else "",
                    "ok": int(ok),
                    "price_quote_per_base": price_quote_per_base(
                        direction, amount_in, amount_out, base_decimals, quote_decimals
                    ) if ok else "",
                    "book_id": book_id if ok and pool_config["type"] == "hyfi_direct" else "",
                    "staleness_fee_raw": fee if ok and pool_config["type"] == "hyfi_direct" else "",
                })
    return rows


def validate_token_decimals(w3, token, expected):
    if token == NATIVE:
        actual = 18
    else:
        actual = w3.eth.contract(address=token, abi=json.loads(ERC20_ABI)).functions.decimals().call()
    if actual != expected:
        raise ValueError(f"{token} decimals: config says {expected}, chain says {actual}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-c", "--chain", required=True, choices=sorted(CHAINS),
                        help="Chain in script/python/config.py")
    parser.add_argument("-p", "--pair", required=True,
                        help="Pair name within the selected chain")
    parser.add_argument("--output", type=Path, help="CSV path (default: beside this script)")
    parser.add_argument("--interval", type=float, default=10, help="Seconds between samples")
    parser.add_argument("--once", action="store_true", help="Write one sample and stop")
    args = parser.parse_args()
    if args.interval <= 0:
        parser.error("--interval must be positive")

    load_dotenv()
    chain_config = CHAINS[args.chain]
    if args.pair not in chain_config["pairs"]:
        parser.error(f"Unknown pair {args.pair!r} on {args.chain}; choose from {', '.join(chain_config['pairs'])}")
    pair_config = chain_config["pairs"][args.pair]
    benchmark_config = pair_config.get("benchmark")
    if not benchmark_config:
        parser.error(f"{args.pair} has no benchmark settings in script/python/config.py")
    rpc_env = chain_config["rpc_env_var"]
    rpc_url = os.getenv(rpc_env)
    if not rpc_url:
        parser.error(f"Set {rpc_env} in the environment or .env")
    base_config = chain_config["tokens"][pair_config["base"]]
    quote_config = chain_config["tokens"][pair_config["quote"]]
    base, quote = address(base_config["addr"]), address(quote_config["addr"])
    if base == quote:
        parser.error("Base and quote tokens must differ")
    base_decimals, quote_decimals = int(base_config["decs"]), int(quote_config["decs"])
    pools = prepare_pools(benchmark_config, pair_config, chain_config["contracts"]["hyfi"], base, quote)
    w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 90}))
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    chain_id = chain_config["chain_id"]
    if w3.eth.chain_id != chain_id:
        parser.error(f"RPC chain ID {w3.eth.chain_id} does not match config {chain_id}")
    validate_token_decimals(w3, base, base_decimals)
    validate_token_decimals(w3, quote, quote_decimals)
    quoter_addr = address(chain_config["contracts"].get("benchmark_quoter", ""))
    if not w3.eth.get_code(quoter_addr):
        parser.error(f"No BenchmarkQuoter contract at {quoter_addr}")
    for entry, pool in pools:
        if entry["type"] == "hyfi_direct" and not w3.eth.get_code(pool[5]):
            parser.error(f"No HyFi contract at {pool[5]}")
    source_name = pair_config["price_source"]
    if source_name not in PRICE_SOURCES:
        parser.error(f"Unknown price_source {source_name!r} for {args.pair}")
    PRICE_SOURCES[source_name].check_env(pair_config)
    contract = w3.eth.contract(address=quoter_addr, abi=json.loads(BENCHMARK_QUOTER_ABI))
    enabled_types = {entry["type"] for entry, _ in pools}
    for kind, getter in (("v3", "v3Quoter"), ("v4", "v4Quoter")):
        if kind in enabled_types:
            venue_quoter = getattr(contract.functions, getter)().call()
            if not w3.eth.get_code(venue_quoter):
                parser.error(f"{kind} is enabled but BenchmarkQuoter's {getter} has no code at {venue_quoter}")
    safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", args.pair)
    output = args.output or Path(__file__).with_name(f"bench_{args.chain}_{safe_name}.csv")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() and output.stat().st_size:
        with output.open(newline="") as file:
            if next(csv.reader(file)) != CSV_HEADERS:
                parser.error(f"CSV header in {output} does not match this benchmark version")
    startup_block = w3.eth.get_block("latest")
    base_multiplier = get_token_multiplier(w3, base_config, base, startup_block.number)
    quote_multiplier = get_token_multiplier(w3, quote_config, quote, startup_block.number)
    last_multiplier_check = time.monotonic()
    print(f"Sampling {args.pair} on chain {chain_id} into {output}", flush=True)

    while True:
        try:
            block = w3.eth.get_block("latest")
            if time.monotonic() - last_multiplier_check >= MULTIPLIER_CHECK_INTERVAL_S:
                current_base = get_token_multiplier(w3, base_config, base, block.number)
                current_quote = get_token_multiplier(w3, quote_config, quote, block.number)
                if current_base != base_multiplier or current_quote != quote_multiplier:
                    raise MultiplierChangedError(
                        f"Token multiplier changed at block {block.number}: "
                        f"{pair_config['base']} {base_multiplier} -> {current_base}, "
                        f"{pair_config['quote']} {quote_multiplier} -> {current_quote}"
                    )
                last_multiplier_check = time.monotonic()
            underlying_base_usd, underlying_quote_usd = reference_prices(pair_config, benchmark_config)
            base_usd = underlying_base_usd * base_multiplier
            quote_usd = underlying_quote_usd * quote_multiplier
            rows = sample(contract, block, chain_id, args.pair, pools, base, quote,
                          base_decimals, quote_decimals, base_usd, quote_usd,
                          base_multiplier, quote_multiplier)
            header = not output.exists() or output.stat().st_size == 0
            with output.open("a", newline="") as file:
                writer = csv.DictWriter(file, fieldnames=CSV_HEADERS)
                if header:
                    writer.writeheader()
                writer.writerows(rows)
            successes = sum(row["ok"] for row in rows)
            print(f"block {block.number}: {successes}/{len(rows)} quotes succeeded", flush=True)
        except KeyboardInterrupt:
            break
        except MultiplierChangedError:
            raise
        except Exception as error:
            print(f"Sample failed: {error}", file=sys.stderr, flush=True)
            if args.once:
                raise
        if args.once:
            break
        try:
            time.sleep(args.interval)
        except KeyboardInterrupt:
            break


if __name__ == "__main__":
    main()
