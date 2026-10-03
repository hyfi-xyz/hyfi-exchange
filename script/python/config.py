"""
Configuration for the book updater and quote benchmark.

Structure:
    CHAINS[chain_name] = {
        'chain_id':    expected EVM chain id (sanity-checked against the RPC),
        'rpc_env_var': name of the env var holding the RPC URL (same vars foundry.toml uses),
        'sleep_s':     seconds to sleep at the end of every update loop,
        'tx': {
            'timeout_s':           seconds to wait for a tx receipt before fee-bumping,
            'fee_bump_multiplier_d': factor applied to both maxFee and maxPriorityFee per bump
                                     (must be >= 1.1 for nodes to accept the replacement),
            'max_fee_gwei_d':      absolute cap on maxFeePerGas - a gas spike can never
                                   spend past this,
            'priority_fee_gwei_d': floor for maxPriorityFeePerGas,
            'max_attempts':        total send attempts (1 initial + bumps) before giving up,
        },
        'contracts': { name -> address },   # must include 'hyfi'; benchmark uses 'benchmark_quoter'
        'tokens':    { name -> {'addr': address, 'decs': decimals} },  # native token = zero address
        'pairs': {
            'BASE-QUOTE': {                 # key convention: BASE-QUOTE (CEX-style symbol)
                'base'/'quote':          token names resolved through 'tokens',
                'fee'/'tick_spacing':    PoolKey fields (defaults 0 / 1),
                'price_source':          key into price_sources.PRICE_SOURCES; the pair dict
                                         itself is passed to the source, so include the
                                         source-specific keys ('stock_symbol', 'spot_pair',
                                         'base_leg'/'quote_leg') here too,
                'ask_liquidity_base_d':  base tokens (nominal) on the single ask tip tick,
                'bid_liquidity_quote_d': quote tokens (nominal) on the single bid tip tick,
                'maker_fee_pct_d':       maker spread applied to the source price, in percent
                                         (e.g. D('0.1') = 0.1%); worsens the price on both
                                         sides (ask up, bid down) applied right after the
                                         source price is fetched, before tip conversion,
                'max_book_age_s':        push a refresh even if the book is unchanged once
                                         the on-chain timestamp is older than this,
                'empty_book_after_failures': after this many consecutive price-source
                                         failures, push an empty book (all ticks zero) so
                                         trades revert instead of filling at a stale price,
                'benchmark': {
                    'quote_usd':       USD value of one underlying quote token (defaults to 1),
                    'pools':           benchmark venues; HyFi direct uses this pair's PoolKey,
                },
            },
        },
    }

tickWidth / baseLiqUnit / baseIsCurrency0 / feePerSecond are NOT configured here - they are
read from the hook's on-chain pairConfig at startup (single source of truth).

Amount-variable naming: *_d = nominal decimal amounts, *_w = wei amounts.
"""

import decimal as dec

D = dec.Decimal

NATIVE = '0x0000000000000000000000000000000000000000'

CHAINS = {
    'robin': {
        'chain_id': 4663,
        'rpc_env_var': 'RPC_URL_ROBIN',
        'sleep_s': 5,
        'tx': {
            'timeout_s': 30,
            'fee_bump_multiplier_d': D('1.5'),
            'max_fee_gwei_d': D('50'),
            'priority_fee_gwei_d': D('0.001'),
            'max_attempts': 5,
        },
        'contracts': {
            'hyfi': '0x2AC29f18B22a12917D4653406B0D2Fe7B592A888',
            'benchmark_quoter': '0x99755A76b6d2C4c1daE6d04b31D3086D6d3947E5',
        },
        'tokens': {
            'ETH': {'addr': NATIVE, 'decs': 18},
            'USDG': {'addr': '0x5fc5360D0400a0Fd4f2af552ADD042D716F1d168', 'decs': 6},
            'NVDA': {'addr': '0xd0601CE157Db5bdC3162BbaC2a2C8aF5320D9EEC', 'decs': 18, 'multiplier_fn': 'uiMultiplier'},
        },
        'pairs': {
            'NVDA-USDG': {
                'base': 'NVDA',
                'quote': 'USDG',
                'fee': 0,
                'tick_spacing': 1,
                'price_source': 'alpaca',
                'stock_symbol': 'NVDA',
                'ask_liquidity_base_d': D('67'),
                'bid_liquidity_quote_d': D('15000'),
                'maker_fee_pct_d': D('0.05'),
                'max_book_age_s': 20,
                'empty_book_after_failures': 10,
                'benchmark': {
                    'pools': [
                        {'name': 'HyFi direct', 'type': 'hyfi_direct'},
                        {'name': 'Uniswap v3 0.05%', 'type': 'v3', 'fee': 500, 'enabled': True},
                        {'name': 'Uniswap v4 0.3%', 'type': 'v4', 'fee': 3000, 'tick_spacing': 60, 'enabled': True},
                        {'name': 'Uniswap v4 0.01%', 'type': 'v4', 'fee': 100, 'tick_spacing': 1},
                        {'name': 'Uniswap v4 0.0375%', 'type': 'v4', 'fee': 375, 'tick_spacing': 4},
                        {'name': 'Uniswap v4 hook 80A6', 'type': 'v4', 'fee': 0, 'tick_spacing': 1, 'hooks': '0x80A6857A9efB62108B69650C1605632A201e40c4'},
                        {'name': 'Uniswap v4 hook 6662 (dynamic fee)', 'type': 'v4', 'fee': 0x800000, 'tick_spacing': 10, 'hooks': '0x66622f77B797D506e5376F7798b67ab288966080'},
                    ],
                },
            },
            'ETH-USDG': {
                'base': 'ETH',
                'quote': 'USDG',
                'fee': 0,
                'tick_spacing': 1,
                'price_source': 'binance',
                'spot_pair': 'ETHUSDC',
                'ask_liquidity_base_d': D('0.5'),
                'bid_liquidity_quote_d': D('1500'),
                'maker_fee_pct_d': D('0.1'),
                'max_book_age_s': 20,
                'empty_book_after_failures': 10,
            },
        },
    },
    'base': {
        'chain_id': 8453,
        'rpc_env_var': 'RPC_URL_BASE',
        'sleep_s': 5,
        'tx': {
            'timeout_s': 30,
            'fee_bump_multiplier_d': D('1.5'),
            'max_fee_gwei_d': D('50'),
            'priority_fee_gwei_d': D('0.001'),
            'max_attempts': 5,
        },
        'contracts': {
            'hyfi': '0xB23F731949145E158E656e1Abe128c5e617A6888',
            'benchmark_quoter': '0x7dfC1523665Dd355fBF5BB80bD855dde97719210',
        },
        'tokens': {
            'ETH': {'addr': NATIVE, 'decs': 18},
            'USDC': {'addr': '0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913', 'decs': 6},
            'NVDAc': {'addr': '0xb20000000000000000000078ee7ce2fE4908108C', 'decs': 8, 'multiplier_fn': 'multiplier'},
        },
        'pairs': {
            'NVDAc-USDC': {
                'base': 'NVDAc',
                'quote': 'USDC',
                'fee': 0,
                'tick_spacing': 1,
                'price_source': 'alpaca',
                'stock_symbol': 'NVDA',
                'ask_liquidity_base_d': D('67'),
                'bid_liquidity_quote_d': D('15000'),
                'maker_fee_pct_d': D('0.05'),
                'max_book_age_s': 20,
                'empty_book_after_failures': 10,
                'benchmark': {
                    'pools': [
                        {'name': 'HyFi direct', 'type': 'hyfi_direct'},
                        {'name': 'Uniswap v4 0.99%', 'type': 'v4', 'fee': 9900, 'tick_spacing': 99},
                        {'name': 'Uniswap v4 3%', 'type': 'v4', 'fee': 30000, 'tick_spacing': 300},
                        {'name': 'Uniswap v3 0.3%', 'type': 'v3', 'fee': 3000},
                    ],
                },
            },
        },
    },
}
