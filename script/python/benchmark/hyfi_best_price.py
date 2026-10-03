#!/usr/bin/env python3
"""Report how often HyFi has the best quote at each order size and direction.

Set CSV_FILENAME below, then run:
    python script/python/benchmark/hyfi_best_price.py
"""

import csv
from pathlib import Path

from analyze import analyze


CSV_FILENAME = "bench_robin_NVDA-USDG.csv"
HYFI_POOL = "HyFi direct"


def main():
    csv_path = Path(__file__).resolve().parent / CSV_FILENAME
    try:
        with csv_path.open(newline="") as file:
            stats = analyze(csv.DictReader(file), HYFI_POOL)
    except (OSError, ValueError) as error:
        raise SystemExit(f"{csv_path}: {error}") from error

    if not stats:
        raise SystemExit(f"No samples in {csv_path}")

    print(f"CSV: {csv_path}")
    print("Best = largest output for the same input; ties count as best.")
    print("Rate excludes samples without a successful competing quote; a failed HyFi quote counts as not best.")
    print(f"{'Pair':<14} {'USD':>6} {'Side':<5} {'Best/compared':>14} {'Rate':>7} "
          f"{'Sole':>6} {'Tied':>6} {'HyFi failed':>12} {'No competitor':>14}")
    for (_, pair, usd, direction), tally in sorted(stats.items()):
        compared = tally["comparable"]
        best = tally["win"] + tally["tie"]
        rate = f"{best / compared:.1%}" if compared else "n/a"
        print(f"{pair:<14} {usd:>6} {direction:<5} {f'{best}/{compared}':>14} {rate:>7} "
              f"{tally['win']:>6} {tally['tie']:>6} {tally['hyfi_failed']:>12} "
              f"{tally['no_competitor']:>14}")


if __name__ == "__main__":
    main()
