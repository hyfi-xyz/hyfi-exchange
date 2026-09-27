BENCHMARK_QUOTER_ABI = """[
  {
    "type": "constructor",
    "inputs": [
      {
        "name": "v4Quoter_",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "v3Quoter_",
        "type": "address",
        "internalType": "address"
      }
    ],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "batchQuote",
    "inputs": [
      {
        "name": "pools",
        "type": "tuple[]",
        "internalType": "struct BenchmarkQuoter.PoolConfig[]",
        "components": [
          {
            "name": "poolType",
            "type": "uint8",
            "internalType": "enum BenchmarkQuoter.PoolType"
          },
          {
            "name": "t0",
            "type": "address",
            "internalType": "address"
          },
          {
            "name": "t1",
            "type": "address",
            "internalType": "address"
          },
          {
            "name": "fee",
            "type": "uint24",
            "internalType": "uint24"
          },
          {
            "name": "tickSpacing",
            "type": "int24",
            "internalType": "int24"
          },
          {
            "name": "hooks",
            "type": "address",
            "internalType": "address"
          },
          {
            "name": "hookData",
            "type": "bytes",
            "internalType": "bytes"
          }
        ]
      },
      {
        "name": "amtsZeroToOne",
        "type": "uint256[]",
        "internalType": "uint256[]"
      },
      {
        "name": "amtsOneToZero",
        "type": "uint256[]",
        "internalType": "uint256[]"
      }
    ],
    "outputs": [
      {
        "name": "outsZeroToOne",
        "type": "tuple[][]",
        "internalType": "struct BenchmarkQuoter.QuoteResult[][]",
        "components": [
          {
            "name": "amountOut",
            "type": "uint256",
            "internalType": "uint256"
          },
          {
            "name": "success",
            "type": "bool",
            "internalType": "bool"
          },
          {
            "name": "bookId",
            "type": "uint40",
            "internalType": "uint40"
          },
          {
            "name": "stalenessFee",
            "type": "uint256",
            "internalType": "uint256"
          }
        ]
      },
      {
        "name": "outsOneToZero",
        "type": "tuple[][]",
        "internalType": "struct BenchmarkQuoter.QuoteResult[][]",
        "components": [
          {
            "name": "amountOut",
            "type": "uint256",
            "internalType": "uint256"
          },
          {
            "name": "success",
            "type": "bool",
            "internalType": "bool"
          },
          {
            "name": "bookId",
            "type": "uint40",
            "internalType": "uint40"
          },
          {
            "name": "stalenessFee",
            "type": "uint256",
            "internalType": "uint256"
          }
        ]
      }
    ],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "v3Quoter",
    "inputs": [],
    "outputs": [
      {
        "name": "",
        "type": "address",
        "internalType": "contract IQuoterV2"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "v4Quoter",
    "inputs": [],
    "outputs": [
      {
        "name": "",
        "type": "address",
        "internalType": "contract IV4Quoter"
      }
    ],
    "stateMutability": "view"
  }
]"""