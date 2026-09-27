import unittest

from script.python.benchmark.analyze import analyze


def row(sample_id, pool, pool_type, output, *, amount_in=100):
    return {
        "chain_id": "8453", "pair": "BASE-USDC", "sample_id": str(sample_id),
        "notional_usd": "100", "direction": "sell", "pool": pool,
        "pool_type": pool_type, "input_raw": str(amount_in),
        "output_raw": "" if output is None else str(output),
        "ok": "0" if output is None else "1",
    }


class AnalyzeTest(unittest.TestCase):
    def test_counts_wins_ties_losses_failures_and_missing_competitors(self):
        rows = []
        for sample_id, hyfi, competitor in ((1, 105, 100), (2, 100, 100),
                                            (3, None, 100), (4, 120, None), (5, 90, 100)):
            rows.append(row(sample_id, "HyFi direct", "hyfi_direct", hyfi))
            rows.append(row(sample_id, "Other venue", "v3", competitor - 10 if competitor else None))
            rows.append(row(sample_id, "Uniswap", "v4", competitor))

        tally = analyze(rows, "HyFi direct")[(8453, "BASE-USDC", 100, "sell")]
        self.assertEqual({key: tally[key] for key in (
            "samples", "hyfi_ok", "comparable", "win", "tie", "loss", "hyfi_failed", "no_competitor"
        )}, {
            "samples": 5, "hyfi_ok": 4, "comparable": 4, "win": 1,
            "tie": 1, "loss": 1, "hyfi_failed": 1, "no_competitor": 1,
        })

    def test_rejects_different_inputs_in_same_sample(self):
        rows = [row(1, "HyFi direct", "hyfi_direct", 100),
                row(1, "Uniswap", "v4", 110, amount_in=101)]
        with self.assertRaisesRegex(ValueError, "inputs differ"):
            analyze(rows, "HyFi direct")


if __name__ == "__main__":
    unittest.main()
