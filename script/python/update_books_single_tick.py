#!/usr/bin/env python
"""
HyFi book updater - pushes single-tick books (best bid / best ask only) on-chain.

Interim stand-in for the offchain orderbook aggregator: fetches the latest top-of-book
from a price source (Alpaca for tokenised stocks, Binance for crypto) and calls
HyFi.updateBooks with one tick of configured liquidity on each side, in a loop.

Usage (from the repo root, venv created via:
    python3 -m venv venv && venv/bin/pip install -r requirements.txt):

    source venv/bin/activate && python script/python/update_books_single_tick.py \
        -c base -p NVDAc-USDC -hyfi 0x... -al real -bl 15000 -mf 0.05

Only -c/--chain and -p/--pairs are required; -hyfi, -al, -bl, -mf and -mba each
override the corresponding config.py value when given.

Requires in .env:
    PRIVATE_KEY_HYFI_UPDATER   the hook's updater key
    <rpc_env_var>              RPC URL per chain (see config.py, e.g. RPC_URL_ROBIN)
    ALPACA_API_KEY(_SECRET..)  when using the alpaca price source

Behaviour:
    - tickWidth / baseLiqUnit / base_is_c0 are read from the hook at startup
    - liquidity per side comes from config: ask side in base tokens, bid side in quote
      tokens (converted to base liquidity units at the current bid tip each loop).
      --ask_liquidity_base_d / --bid_liquidity_quote_d override a side with either a
      fixed amount or 'real' (size it from the hook's live token balance each loop).
    - unchanged books are not re-pushed until they age past max_book_age_s
    - after N consecutive price-source failures a pair's book is emptied on-chain
    - stuck txs are fee-bumped after tx.timeout_s, capped at tx.max_fee_gwei_d
    - -s/--sleep overrides config.py sleep_s (target seconds between loop starts)
    - -mba/--max-book-age overrides each pair's max_book_age_s (0 refreshes every loop)
    - logs to stdout and script/logs/update_books_<chain>.log

Amount-variable naming: *_d = nominal decimal amounts, *_w = wei amounts.
"""

import argparse
import decimal as dec
import json
import logging
import math
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from eth_abi import encode as abi_encode
from eth_account import Account
from web3 import Web3
from web3.exceptions import TimeExhausted

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from ABIs.hyfi_abi import HYFI_ABI  # noqa: E402
from ABIs.erc20_abi import ERC20_ABI  # noqa: E402
from config import CHAINS  # noqa: E402
from price_sources import PRICE_SOURCES  # noqa: E402

dec.getcontext().prec = 60
D = dec.Decimal

log = logging.getLogger('update_books')

# --- HyFi book constants (must match HyFi.sol) --------------------------------
SCALE = 10 ** 24  # fixed-point scale of tickWidth
TS_SHIFT, ID_SHIFT, CUR_SHIFT, END_SHIFT, LEFT_SHIFT, HEAD_SHIFT = 40, 72, 112, 120, 128, 224
MASK_8, MASK_32, MASK_40, MASK_96 = 0xFF, 0xFFFFFFFF, 0xFFFFFFFFFF, (1 << 96) - 1
MAX_TICK_VALUE = 255
UINT40_MAX = (1 << 40) - 1

# Gas cost tracking
ETH_PRICE_USD = 2500  # Assumed ETH price for $ calculations
start_time = None  # Set in main()
total_gas_cost_usd = D('0')  # Cumulative gas cost in USD


MULTIPLIER_DECIMALS = 18  # RWA token multipliers are always 18-decimal

REAL = 'real'  # liquidity-flag value meaning "size this side from the hook's live balance"


# ------------------------------------------------------------------
# Runtime pair state
# ------------------------------------------------------------------

@dataclass
class Pair:
    name: str
    cfg: dict
    pool_id: bytes
    base_is_currency0: bool
    tick_width: int          # quote-wei per base-wei, x1e24
    base_liq_unit_w: int     # base wei per liquidity unit
    base_dec: int
    quote_dec: int
    ask_units: int           # fixed at startup from a fixed ask amount; 0 when the ask side is 'real'
    ask_liquidity_base_d: object = None   # nominal base amount, or REAL to read the hook's balance
    bid_liquidity_quote_d: object = None  # nominal quote amount, or REAL to read the hook's balance
    maker_fee_pct_d: object = None        # maker spread applied to the source price, in percent
    base_balance_fn: object = None      # () -> hook's base-token wei balance (REAL ask side only)
    quote_balance_fn: object = None     # () -> hook's quote-token wei balance (REAL bid side only)
    base_mult_contract: object = None   # on-chain multiplier of the base token (RWA), or None
    quote_mult_contract: object = None  # on-chain multiplier of the quote token (RWA), or None
    book_id_counter: int = 0  # bumped per update attempt; seeded from chain at startup
    consecutive_failures: int = 0
    emptied: bool = False    # an empty book is currently on-chain for this pair
    last_bid_tip: int = 1    # last pushed tips (skip check + fallback for empty-book updates)
    last_ask_tip: int = 1
    last_bid_units: int = -1  # last pushed unit counts (-1 = nothing pushed yet)
    last_ask_units: int = -1
    last_push_ts: int = 0    # wall clock of the last successful push (for max_book_age_s)


# ------------------------------------------------------------------
# Logging
# ------------------------------------------------------------------

def setup_logging(chain_name):
    logs_dir = SCRIPT_DIR / 'logs'
    logs_dir.mkdir(exist_ok=True)
    fmt = logging.Formatter('%(asctime)s %(levelname)-7s %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    for handler in (
        logging.FileHandler(logs_dir / f'update_books_{chain_name}.log'),
        logging.StreamHandler(sys.stdout),
    ):
        handler.setFormatter(fmt)
        log.addHandler(handler)
    log.setLevel(logging.INFO)


def require(condition, message, *args):
    """Log an error and exit(1) if condition is falsy. Used for startup validation in main()."""
    if not condition:
        log.error(message, *args)
        sys.exit(1)


# ------------------------------------------------------------------
# Book maths
# ------------------------------------------------------------------

def compute_pool_id(currency0, currency1, fee, tick_spacing, hook):
    """keccak256(abi.encode(PoolKey)) exactly as v4's PoolId.toId()."""
    return Web3.keccak(abi_encode(
        ['address', 'address', 'uint24', 'int24', 'address'],
        [currency0, currency1, fee, tick_spacing, hook],
    ))


def price_to_tip(price_d, base_dec, quote_dec, tick_width, round_up):
    """Convert a nominal price (quote per base) to a tip in multiples of tickWidth.
    Bids round down and asks round up so the pushed book is never tighter than the source.
    """
    price_x24 = price_d * D(10 ** quote_dec) * D(SCALE) / D(10 ** base_dec)
    rounding = dec.ROUND_CEILING if round_up else dec.ROUND_FLOOR
    return int((price_x24 / D(tick_width)).to_integral_value(rounding=rounding))


def apply_maker_fee(bid_price_d, ask_price_d, maker_fee_pct_d):
    fee_frac = maker_fee_pct_d / D('100')
    return (bid_price_d * (D('1') - fee_frac), ask_price_d * (D('1') + fee_frac))


def d_to_w(amount_d, decimals):
    """Nominal decimal amount -> wei, truncated."""
    return int(D(amount_d) * D(10 ** decimals))


def w_to_d(amount_w, decimals):
    """Wei -> nominal decimal amount."""
    return D(amount_w) / D(10 ** decimals)


def base_amount_to_units(base_w, base_liq_unit_w):
    return base_w // base_liq_unit_w


def quote_amount_to_units(quote_w, tip, tick_width, base_liq_unit_w):
    """Liquidity units representable by `quote_w` quote wei at the tip's price."""
    base_w = quote_w * SCALE // (tip * tick_width)
    return base_amount_to_units(base_w, base_liq_unit_w)


def side_update(tip, units):
    """A single-tick SideUpdate tuple: all liquidity on tick 0 (the tip)."""
    return (tip, 0, units, 0, 0)  # (tipPrice, endTick, headTicks, wordA, wordB)


def decode_slot0(slot0):
    return {
        'tip': slot0 & MASK_40,
        'ts': (slot0 >> TS_SHIFT) & MASK_32,
        'book_id': (slot0 >> ID_SHIFT) & MASK_40,
        'cur': (slot0 >> CUR_SHIFT) & MASK_8,
        'end': (slot0 >> END_SHIFT) & MASK_8,
        'left': (slot0 >> LEFT_SHIFT) & MASK_96,
        'tick0': (slot0 >> HEAD_SHIFT) & MASK_8,
    }


# ------------------------------------------------------------------
# Startup
# ------------------------------------------------------------------

def resolve_token(chain_cfg, name):
    token = chain_cfg['tokens'][name]
    return Web3.to_checksum_address(token['addr']), token['decs']

def balance_fn(w3, token_addr, holder):
    """Zero-arg callable returning `holder`'s wei balance of `token_addr` (native when 0x0)."""
    if int(token_addr, 16) == 0:
        return lambda: w3.eth.get_balance(holder)
    contract = w3.eth.contract(address=token_addr, abi=json.loads(ERC20_ABI))
    return lambda: contract.functions.balanceOf(holder).call()

def clamp_units(units, pair_name, side, detail):
    """Validate a liquidity-unit count against the uint8 tick range. Returns None if unusable."""
    if units < 1:
        log.error(f'{pair_name}: {side} {detail} maps to 0 liquidity units, skipping')
        return None
    if units > MAX_TICK_VALUE:
        log.warning(f'{pair_name}: {side} liquidity clamped to {MAX_TICK_VALUE} units (wanted {units})')
        return MAX_TICK_VALUE
    return units

def read_multiplier(contract):
    """Current multiplier of an RWA token as a nominal Decimal (1 = no adjustment)."""
    # the ABI built in multiplier_contract has exactly one entry
    return w_to_d(list(contract.functions)[0]().call(), MULTIPLIER_DECIMALS)


def side_liquidity_w(setting, balance_getter, decimals, label):
    """Wei available to a book side, plus a log-friendly description of where it came from."""
    if setting == REAL:
        amount_w = balance_getter()
        return amount_w, f'hook balance {amount_w}'
    return d_to_w(setting, decimals), f'{label}={setting}'


def multiplier_contract(w3, chain_cfg, token_name, addr, pair_name):
    """Web3 contract exposing the RWA token's multiplier fn, or None if the token has none."""
    mult_fn = chain_cfg['tokens'][token_name].get('multiplier_fn')
    if not mult_fn:
        return None
    abi = [{'inputs': [], 'name': mult_fn, 'outputs': [{'type': 'uint256'}], 'stateMutability': 'view', 'type': 'function'}]
    contract = w3.eth.contract(address=addr, abi=abi)
    log.info(f'{pair_name}: {token_name} multiplier ({mult_fn}) = {read_multiplier(contract)}')
    return contract

def setup_pair(w3, hyfi, chain_cfg, name, ask_override, bid_override, maker_fee_override, max_book_age_override=None):
    """Resolve addresses, derive the poolId, and load + validate on-chain pair config."""
    cfg = chain_cfg['pairs'][name].copy()
    if max_book_age_override is not None:
        cfg['max_book_age_s'] = max_book_age_override
    source_name = cfg.get('price_source')
    if source_name not in PRICE_SOURCES:
        raise RuntimeError(f'{name}: unknown price_source {source_name!r}')
    PRICE_SOURCES[source_name].check_env(cfg)

    base_addr, base_dec = resolve_token(chain_cfg, cfg['base'])
    quote_addr, quote_dec = resolve_token(chain_cfg, cfg['quote'])
    base_is_currency0 = int(base_addr, 16) < int(quote_addr, 16)
    c0, c1 = (base_addr, quote_addr) if base_is_currency0 else (quote_addr, base_addr)
    pool_id = compute_pool_id(c0, c1, cfg.get('fee', 0), cfg.get('tick_spacing', 1), hyfi.address)

    tick_width, base_liq_unit_w, fee_per_second, base_is_c0_onchain = hyfi.functions.pairConfig(pool_id).call()
    if tick_width == 0:
        raise RuntimeError(f'{name}: pair not configured on-chain (poolId 0x{pool_id.hex()})')
    if base_is_c0_onchain != base_is_currency0:
        raise RuntimeError(
            f'{name}: on-chain base_is_c0={base_is_c0_onchain} does not match token '
            f'addresses (config base={cfg["base"]}) - check the config'
        )

    ask_liq = ask_override if ask_override is not None else cfg['ask_liquidity_base_d']
    bid_liq = bid_override if bid_override is not None else cfg['bid_liquidity_quote_d']
    maker_fee = maker_fee_override if maker_fee_override is not None else cfg['maker_fee_pct_d']

    # A REAL side is sized from the hook's balance each loop; a fixed ask amount is constant,
    # so validate it once here rather than every loop.
    base_balance_getter = balance_fn(w3, base_addr, hyfi.address) if ask_liq == REAL else None
    quote_balance_getter = balance_fn(w3, quote_addr, hyfi.address) if bid_liq == REAL else None
    ask_units = 0
    if ask_liq != REAL:
        ask_units = base_amount_to_units(d_to_w(ask_liq, base_dec), base_liq_unit_w)
        if not 1 <= ask_units <= MAX_TICK_VALUE:
            raise RuntimeError(
                f'{name}: ask_liquidity_base_d={ask_liq} maps to {ask_units} '
                f'liquidity units (baseLiqUnit={base_liq_unit_w}); must be 1-{MAX_TICK_VALUE}'
            )

    # Seed the per-pair bookId counter from chain so the first push is strictly greater than the
    # stored bookId (the contract requires per-pair bookIds to be monotonically increasing).
    bid_slot0, _, _ = hyfi.functions.getBookSideRaw(pool_id, True).call()
    book_id_counter = decode_slot0(bid_slot0)['book_id']

    # RWA tokens (tokenised stocks) carry an on-chain multiplier that accounts for
    # dividends and splits. Read each loop to adjust the source price on either side.
    base_mult_contract = multiplier_contract(w3, chain_cfg, cfg['base'], base_addr, name)
    quote_mult_contract = multiplier_contract(w3, chain_cfg, cfg['quote'], quote_addr, name)

    pair = Pair(
        name=name, cfg=cfg, pool_id=pool_id, base_is_currency0=base_is_currency0,
        tick_width=tick_width, base_liq_unit_w=base_liq_unit_w,
        base_dec=base_dec, quote_dec=quote_dec, ask_units=ask_units,
        ask_liquidity_base_d=ask_liq, bid_liquidity_quote_d=bid_liq, maker_fee_pct_d=maker_fee,
        base_balance_fn=base_balance_getter, quote_balance_fn=quote_balance_getter,
        base_mult_contract=base_mult_contract, quote_mult_contract=quote_mult_contract,
        book_id_counter=book_id_counter,
    )
    ask_src = 'hook balance' if ask_liq == REAL else f'{ask_liq} ({ask_units} units)'
    bid_src = 'hook balance' if bid_liq == REAL else str(bid_liq)
    log.info(
        f'{name} ready: poolId=0x{pool_id.hex()} tickWidth={tick_width} baseLiqUnit={base_liq_unit_w} feePerSecond={fee_per_second} '
        f'base_is_c0={base_is_currency0} decimals={base_dec}/{quote_dec} ask={ask_src} bid={bid_src} makerFee={maker_fee}% maxBookAge={cfg["max_book_age_s"]}s bookId={book_id_counter} source={source_name}'
    )
    return pair


# ------------------------------------------------------------------
# Per-loop pair update construction
# ------------------------------------------------------------------

def build_pair_update(pair, now_ts):
    """Fetch prices and build this pair's PairUpdate tuple.
    Returns the update tuple, or None when nothing needs pushing (price unchanged and the
    book isn't yet due a staleness refresh, price source down but not yet at the empty-book
    threshold, or the book is already emptied).
    """
    cfg = pair.cfg
    try:
        bid_price_d, ask_price_d, _ = PRICE_SOURCES[cfg['price_source']].get_top_of_book(cfg)
        log.info(f'{pair.name}: source book bid={bid_price_d} ask={ask_price_d}')
    except Exception as e:  # noqa: BLE001 - any source failure follows the same path
        pair.consecutive_failures += 1
        log.warning(f'{pair.name}: price source failed ({pair.consecutive_failures} consecutive): {e}')
        if pair.consecutive_failures >= cfg['empty_book_after_failures'] and not pair.emptied:
            log.error(f'{pair.name}: {pair.consecutive_failures} consecutive failures - pushing empty book to disable trading')
            return _empty_update(pair)
        return None

    pair.consecutive_failures = 0
    if bid_price_d >= ask_price_d:
        log.warning(f'{pair.name}: crossed/locked source book (bid={bid_price_d} ask={ask_price_d}), skipping')
        return None

    # Adjust for RWA token multipliers (dividends / splits). The source prices the underlying
    # stock; the price is quote-per-base, so a base-side multiplier scales it up and a
    # quote-side multiplier scales it down (the quote token itself is worth more).
    # Pool currency0/1 ordering is irrelevant here - tips are per nominal base/quote.
    if pair.base_mult_contract is not None:
        mult_d = read_multiplier(pair.base_mult_contract)
        bid_price_d *= mult_d
        ask_price_d *= mult_d
        log.info(f'{pair.name}: base multiplier={mult_d} adjusted bid={bid_price_d} ask={ask_price_d}')
    if pair.quote_mult_contract is not None:
        mult_d = read_multiplier(pair.quote_mult_contract)
        bid_price_d /= mult_d
        ask_price_d /= mult_d
        log.info(f'{pair.name}: quote multiplier={mult_d} adjusted bid={bid_price_d} ask={ask_price_d}')

    bid_price_d, ask_price_d = apply_maker_fee(bid_price_d, ask_price_d, pair.maker_fee_pct_d)
    bid_tip = price_to_tip(bid_price_d, pair.base_dec, pair.quote_dec, pair.tick_width, round_up=False)
    ask_tip = price_to_tip(ask_price_d, pair.base_dec, pair.quote_dec, pair.tick_width, round_up=True)
    if not 1 <= bid_tip <= UINT40_MAX or not 1 <= ask_tip <= UINT40_MAX:
        log.error(f'{pair.name}: tip out of range (bid={bid_tip} ask={ask_tip}) - check tickWidth vs price magnitude')
        return None

    # Liquidity per side: a fixed nominal amount, or whatever the hook actually holds right now
    # (rounded down to whole liquidity units by the unit conversions below).
    ask_base_w, ask_detail = side_liquidity_w(pair.ask_liquidity_base_d, pair.base_balance_fn, pair.base_dec, 'ask_liquidity_base_d')
    bid_quote_w, bid_detail = side_liquidity_w(pair.bid_liquidity_quote_d, pair.quote_balance_fn, pair.quote_dec, 'bid_liquidity_quote_d')

    ask_units = clamp_units(base_amount_to_units(ask_base_w, pair.base_liq_unit_w), pair.name, 'ask', ask_detail)
    if ask_units is None:
        return None
    bid_units = clamp_units(
        quote_amount_to_units(bid_quote_w, bid_tip, pair.tick_width, pair.base_liq_unit_w),
        pair.name, 'bid', bid_detail,
    )
    if bid_units is None:
        return None

    # We only ever push the single top tick per side, so the on-chain book is fully described by
    # its tips and unit counts. Skip re-pushing when neither changed and the book isn't yet due a
    # staleness refresh (all tracked in memory from the last push - no on-chain read needed).
    if (not pair.emptied
            and bid_tip == pair.last_bid_tip and ask_tip == pair.last_ask_tip
            and bid_units == pair.last_bid_units and ask_units == pair.last_ask_units
            and now_ts - pair.last_push_ts < cfg['max_book_age_s']):
        log.info(f'{pair.name}: book unchanged and fresh (age {now_ts - pair.last_push_ts}s), skipping')
        return None

    pair.book_id_counter += 1
    update = (
        pair.pool_id, pair.book_id_counter,
        side_update(bid_tip, bid_units),
        side_update(ask_tip, ask_units),
    )
    log.info(f'{pair.name}: bookId={pair.book_id_counter} bidTip={bid_tip} ({bid_units} units) askTip={ask_tip} ({ask_units} units)')
    return update


def _empty_update(pair):
    """A PairUpdate with zero liquidity on both sides - trades revert until the next real book."""
    pair.book_id_counter += 1
    return (pair.pool_id, pair.book_id_counter, side_update(pair.last_bid_tip, 0), side_update(pair.last_ask_tip, 0))


def calculate_gas_cost_and_hourly_rate(receipt, max_fee_w):
    """Calculate gas cost in USD and burn rates (hourly and daily), update global cumulative cost.
    
    Returns (gas_cost_usd, cost_per_hour_usd, cost_per_day_usd).
    """
    global total_gas_cost_usd
    
    gas_used = receipt['gasUsed']
    effective_gas_price_w = receipt.get('effectiveGasPrice', max_fee_w)
    gas_cost_w = gas_used * effective_gas_price_w
    gas_cost_eth = w_to_d(gas_cost_w, 18)
    gas_cost_usd = gas_cost_eth * D(ETH_PRICE_USD)
    
    total_gas_cost_usd += gas_cost_usd
    
    elapsed_s = time.time() - start_time
    hours_elapsed = elapsed_s / 3600
    cost_per_hour = total_gas_cost_usd / D(hours_elapsed) if hours_elapsed > 0 else D('0')
    cost_per_day = cost_per_hour * D('24')
    
    return gas_cost_usd, cost_per_hour, cost_per_day


# ------------------------------------------------------------------
# Tx submission with stuck-tx fee bumping
# ------------------------------------------------------------------

def send_update_books(w3, hyfi, account, tx_cfg, updates, batch_ts):
    """Send updateBooks and wait for the receipt, fee-bumping stuck txs.

    After tx_cfg['timeout_s'] without a receipt, both fees are multiplied by
    fee_bump_multiplier_d and the same-nonce tx is re-broadcast. maxFeePerGas is hard-capped
    at max_fee_gwei_d; if the cap makes a replacement impossible, gives up with an error.
    
    Tracks cumulative gas costs and logs $ spent and $ per hour on tx confirmation.
    """

    # The gas estimate uses the latest block from the RPC, which is potentially 1 or more blocks behind
    # the real tip, and is certainly behind what the timestamp of the block the tx executes in will be,
    # so need to use a lower timestamp to make sure it doesn't revert on the estimate_gas fcn
    fn = hyfi.functions.updateBooks(updates, batch_ts-3)
    gas = int(fn.estimate_gas({'from': account.address}) * 1.2)
    fn = hyfi.functions.updateBooks(updates, batch_ts)
    nonce = w3.eth.get_transaction_count(account.address, 'pending')

    base_fee_w = w3.eth.get_block('latest')['baseFeePerGas']
    priority_floor_w = d_to_w(tx_cfg['priority_fee_gwei_d'], 9)
    try:
        priority_fee_w = max(w3.eth.max_priority_fee, priority_floor_w)
    except Exception:  # noqa: BLE001 - not all RPCs expose eth_maxPriorityFeePerGas
        priority_fee_w = priority_floor_w
    max_fee_cap_w = d_to_w(tx_cfg['max_fee_gwei_d'], 9)
    max_fee_w = min(2 * base_fee_w + priority_fee_w, max_fee_cap_w)
    bump_d = tx_cfg['fee_bump_multiplier_d']

    for attempt in range(1, tx_cfg['max_attempts'] + 1):
        tx = fn.build_transaction({
            'from': account.address,
            'nonce': nonce,
            'gas': gas,
            'maxFeePerGas': max_fee_w,
            'maxPriorityFeePerGas': min(priority_fee_w, max_fee_w),
            'chainId': w3.eth.chain_id,
        })
        tx_hash = w3.eth.send_raw_transaction(account.sign_transaction(tx).raw_transaction)
        log.info(f'updateBooks sent (attempt {attempt}/{tx_cfg["max_attempts"]}): {tx_hash.hex()} maxFee={max_fee_w / 1e9:.3f} gwei')
        try:
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=tx_cfg['timeout_s'])
        except TimeExhausted:
            new_max_fee_w = min(int(max_fee_w * bump_d), max_fee_cap_w)
            if new_max_fee_w < int(max_fee_w * 1.1):
                raise RuntimeError(
                    f'tx {tx_hash.hex()} stuck and fee cap {tx_cfg["max_fee_gwei_d"]} gwei '
                    f'prevents a valid replacement - raise the cap or wait'
                )
            log.warning(f'tx {tx_hash.hex()} stuck after {tx_cfg["timeout_s"]}s, bumping fee {max_fee_w / 1e9:.3f} -> {new_max_fee_w / 1e9:.3f} gwei')
            max_fee_w = new_max_fee_w
            priority_fee_w = int(priority_fee_w * bump_d)
            continue
        if receipt['status'] != 1:
            raise RuntimeError(f'updateBooks reverted on-chain: {tx_hash.hex()}')
        
        gas_cost_usd, cost_per_hour, cost_per_day = calculate_gas_cost_and_hourly_rate(receipt, max_fee_w)
        log.info(f'updateBooks confirmed in block {receipt["blockNumber"]} (gas used {receipt["gasUsed"]}): 0x{tx_hash.hex()} | ${cost_per_hour:.2f}/hour (${cost_per_day:.2f}/day)')
        return receipt
    raise RuntimeError(f'updateBooks not confirmed after {tx_cfg["max_attempts"]} attempts')


# ------------------------------------------------------------------
# Main loop
# ------------------------------------------------------------------

def run_loop(w3, hyfi, account, chain_cfg, pairs, sleep_s):
    while True:
        loop_start = time.time()
        try:
            # A single wall-clock timestamp covers the whole batch: price fetches are
            # near-instantaneous relative to the staleness-fee granularity (seconds).
            now_ts = int(time.time())
            included = []
            for pair in pairs:
                update = build_pair_update(pair, now_ts)
                if update is not None:
                    included.append((pair, update))

            if included:
                send_update_books(w3, hyfi, account, chain_cfg['tx'], [u for _, u in included], now_ts)
                for pair, update in included:
                    pair.last_bid_tip, pair.last_ask_tip = update[2][0], update[3][0]
                    pair.last_bid_units, pair.last_ask_units = update[2][2], update[3][2]
                    pair.last_push_ts = now_ts
                    pair.emptied = update[2][2] == 0 and update[3][2] == 0  # both headTicks empty
        except Exception as e:  # noqa: BLE001 - the loop must survive any single failure
            log.error(f'update loop error: {e}', exc_info=True)

        elapsed = time.time() - loop_start
        time.sleep(max(0, sleep_s - elapsed))


def liquidity_arg(value):
    """argparse type for the per-side liquidity flags: 'real' or a positive nominal amount."""
    if value.strip().lower() == REAL:
        return REAL
    try:
        amount = D(value)
    except dec.InvalidOperation:
        raise argparse.ArgumentTypeError(f"expected 'real' or a number, got {value!r}") from None
    if not amount.is_finite() or amount <= 0:
        raise argparse.ArgumentTypeError(f'expected a positive amount, got {value!r}')
    return amount


def maker_fee_arg(value):
    """argparse type for --maker_fee_pct_d: a percentage in [0, 100)."""
    try:
        pct = D(value)
    except dec.InvalidOperation:
        raise argparse.ArgumentTypeError(f'expected a number, got {value!r}') from None
    if not pct.is_finite() or not 0 <= pct < 100:
        raise argparse.ArgumentTypeError(f'expected a percentage in [0, 100), got {value!r}')
    return pct


def address_arg(value):
    """argparse type for an EVM address, normalised to its checksummed form."""
    try:
        return Web3.to_checksum_address(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f'expected an EVM address, got {value!r}') from None


def main():
    global start_time
    
    parser = argparse.ArgumentParser(description='Push single-tick HyFi book updates in a loop')
    parser.add_argument('-c', '--chain', required=True, choices=sorted(CHAINS.keys()))
    parser.add_argument('-p', '--pairs', required=True, help='comma-separated pair names, e.g. NVDA-USDG,ETH-USDG')
    parser.add_argument('-s', '--sleep', type=float, metavar='SECONDS', help='target seconds between update-loop starts (default: config.py sleep_s)')
    parser.add_argument('-mba', '--max-book-age', type=int, metavar='SECONDS',
                        help='refresh an unchanged book after this many seconds; 0 refreshes every loop (default: config.py max_book_age_s)')
    parser.add_argument(
        '-hyfi', '--hyfi', type=address_arg, metavar='ADDRESS',
        help="the HyFi hook address, overriding contracts['hyfi'] in config.py",
    )
    parser.add_argument(
        '-al', '--ask_liquidity_base_d', type=liquidity_arg, metavar="real|AMOUNT",
        help="ask-side liquidity in base tokens: 'real' to size it from the hook's live base "
             'balance, or a nominal amount overriding config.py (default: config.py)',
    )
    parser.add_argument(
        '-bl', '--bid_liquidity_quote_d', type=liquidity_arg, metavar="real|AMOUNT",
        help="bid-side liquidity in quote tokens: 'real' to size it from the hook's live quote "
             'balance, or a nominal amount overriding config.py (default: config.py)',
    )
    parser.add_argument(
        '-mf', '--maker_fee_pct_d', type=maker_fee_arg, metavar='PERCENT',
        help='maker spread applied to the source price, in percent (e.g. 0.05 = 0.05%%); '
             'worsens both sides. Overrides config.py (default: config.py)',
    )
    args = parser.parse_args()
    if args.sleep is not None and (not math.isfinite(args.sleep) or args.sleep < 0):
        parser.error('--sleep must be a non-negative finite number')
    if args.max_book_age is not None and args.max_book_age < 0:
        parser.error('--max-book-age must be a non-negative integer')

    setup_logging(args.chain)
    load_dotenv(SCRIPT_DIR.parent.parent / '.env')
    start_time = time.time()

    chain_cfg = CHAINS[args.chain]
    sleep_s = args.sleep if args.sleep is not None else chain_cfg['sleep_s']
    pair_names = [p.strip() for p in args.pairs.split(',') if p.strip()]
    unknown = [p for p in pair_names if p not in chain_cfg['pairs']]
    require(not unknown, 'Unknown pairs for chain %s: %s (configured: %s)', args.chain, ', '.join(unknown), ', '.join(chain_cfg['pairs']))

    private_key = os.getenv('PRIVATE_KEY_HYFI_UPDATER')
    require(private_key, 'PRIVATE_KEY_HYFI_UPDATER not set in .env')
    rpc_url = os.getenv(chain_cfg['rpc_env_var'])
    require(rpc_url, '%s not set in .env', chain_cfg['rpc_env_var'])
    hyfi_address = args.hyfi if args.hyfi is not None else chain_cfg['contracts'].get('hyfi')
    require(hyfi_address, "contracts['hyfi'] not set in config for chain %s (or pass -hyfi)", args.chain)

    w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={'timeout': 30}))
    chain_id = w3.eth.chain_id
    require(chain_id == chain_cfg['chain_id'], 'RPC chain id %d != configured %d', chain_id, chain_cfg['chain_id'])

    account = Account.from_key(private_key)
    hyfi = w3.eth.contract(address=Web3.to_checksum_address(hyfi_address), abi=json.loads(HYFI_ABI))

    onchain_updater = hyfi.functions.updater().call()
    require(onchain_updater.lower() == account.address.lower(), 'Key address %s is not the hook updater (%s)', account.address, onchain_updater)

    balance_w = w3.eth.get_balance(account.address)
    log.info(f'Starting updater on {args.chain} (chainId {chain_id}): hook={hyfi.address} updater={account.address} balance={w_to_d(balance_w, 18):.6f} ETH pairs={", ".join(pair_names)} sleep={sleep_s}s')
    pairs = [
        setup_pair(w3, hyfi, chain_cfg, name, args.ask_liquidity_base_d, args.bid_liquidity_quote_d,
                   args.maker_fee_pct_d, args.max_book_age)
        for name in pair_names
    ]

    try:
        run_loop(w3, hyfi, account, chain_cfg, pairs, sleep_s)
    except KeyboardInterrupt:
        log.info('Interrupted, shutting down')


if __name__ == '__main__':
    main()
