#!/usr/bin/env python3
"""Report how often HyFi direct beats the best successful competing quote."""

import argparse
import csv
from collections import defaultdict
from pathlib import Path


def analyze(rows, hyfi_name):
    samples = defaultdict(dict)
    for row in rows:
        key = (row["chain_id"], row["pair"], row["sample_id"], row["notional_usd"], row["direction"])
        if row["pool"] in samples[key]:
            raise ValueError(f"Duplicate pool {row['pool']} in sample {key}")
        samples[key][row["pool"]] = row

    stats = defaultdict(lambda: defaultdict(int))
    for (chain_id, pair, _, usd, direction), pools in samples.items():
        if hyfi_name not in pools:
            raise ValueError(f"Missing {hyfi_name} row in a sample")
        hyfi = pools[hyfi_name]
        if hyfi["pool_type"] != "hyfi_direct":
            raise ValueError(f"{hyfi_name} is not a HyFi direct quote")
        inputs = {int(row["input_raw"]) for row in pools.values()}
        if len(inputs) != 1:
            raise ValueError("Pool inputs differ within a sample; output comparison is invalid")
        tally = stats[(int(chain_id), pair, int(usd), direction)]
        tally["samples"] += 1
        if hyfi["ok"] == "1":
            tally["hyfi_ok"] += 1
        competitors = [row for name, row in pools.items()
                       if name != hyfi_name and not row["pool_type"].startswith("hyfi") and row["ok"] == "1"]
        if not competitors:
            tally["no_competitor"] += 1
            continue
        tally["comparable"] += 1
        if hyfi["ok"] != "1":
            tally["hyfi_failed"] += 1
            continue
        best_competitor = max(int(row["output_raw"]) for row in competitors)
        hyfi_output = int(hyfi["output_raw"])
        if hyfi_output > best_competitor:
            tally["win"] += 1
        elif hyfi_output == best_competitor:
            tally["tie"] += 1
        else:
            tally["loss"] += 1
    return stats


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--hyfi", required=True, help="Pool name for the HyFi direct quote")
    args = parser.parse_args()
    with args.csv_path.open(newline="") as file:
        rows = list(csv.DictReader(file))
    if not rows:
        parser.error("CSV contains no samples")
    stats = analyze(rows, args.hyfi)
    print("Chain  Pair  USD  Direction  Samples  HyFi OK  Comparable  Win  Tie  Loss  HyFi failed  No competitor  Best or tied")
    for (chain_id, pair, usd, direction), tally in sorted(stats.items()):
        comparable = tally["comparable"]
        rate = f"{100 * (tally['win'] + tally['tie']) / comparable:.1f}%" if comparable else "n/a"
        print(f"{chain_id:<6} {pair:<14} {usd:<4} {direction:<9} {tally['samples']:<8} {tally['hyfi_ok']:<8} "
              f"{comparable:<11} {tally['win']:<4} {tally['tie']:<4} {tally['loss']:<5} "
              f"{tally['hyfi_failed']:<12} {tally['no_competitor']:<14} {rate}")


if __name__ == "__main__":
    main()
