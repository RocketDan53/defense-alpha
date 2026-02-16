#!/usr/bin/env python3
"""
Run signal-response benchmarks.

Predefined benchmarks:
  - space_force:        US Space Force Establishment (Dec 2019)
  - nds_2018:           2018 NDS Great Power Competition pivot
  - ukraine_drones_2022: Post-Ukraine drone/autonomous systems surge

Usage:
    # Run all benchmarks
    python scripts/run_benchmarks.py

    # Run specific benchmark
    python scripts/run_benchmarks.py --benchmark space_force

    # Run with fewer bootstrap iterations (faster)
    python scripts/run_benchmarks.py --benchmark nds_2018 --bootstrap 100

    # Skip bootstrap (fastest)
    python scripts/run_benchmarks.py --benchmark space_force --bootstrap 0

    # Export results to JSON
    python scripts/run_benchmarks.py --benchmark space_force --output results/

    # List available benchmarks
    python scripts/run_benchmarks.py --list
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from processing.signal_response import (
    BENCHMARKS,
    SignalResponseBenchmark,
    print_report,
)

PROJECT_ROOT = Path(__file__).parent.parent
DB_PATH = PROJECT_ROOT / "data" / "defense_alpha.db"


def main():
    parser = argparse.ArgumentParser(description="Run signal-response benchmarks")
    parser.add_argument(
        "--benchmark", "-b",
        type=str,
        help="Benchmark name (default: run all). Use --list to see options.",
    )
    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="List available benchmarks",
    )
    parser.add_argument(
        "--bootstrap",
        type=int,
        default=1000,
        help="Number of bootstrap iterations (0 to skip, default: 1000)",
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        help="Directory to write JSON results",
    )

    args = parser.parse_args()

    if args.list:
        print("Available benchmarks:")
        print()
        for name, config in BENCHMARKS.items():
            print(f"  {name:<25} {config.signal_name}")
            print(f"  {'':25} Cohort: {', '.join(config.cohort_scores_any)} >= {config.cohort_threshold}")
            print(f"  {'':25} Period: {config.baseline_start} to {config.response_end}")
            print()
        return

    if not DB_PATH.exists():
        print(f"Error: Database not found at {DB_PATH}")
        sys.exit(1)

    # Determine which benchmarks to run
    if args.benchmark:
        if args.benchmark not in BENCHMARKS:
            print(f"Error: Unknown benchmark '{args.benchmark}'")
            print(f"Available: {', '.join(BENCHMARKS.keys())}")
            sys.exit(1)
        to_run = {args.benchmark: BENCHMARKS[args.benchmark]}
    else:
        to_run = BENCHMARKS

    output_dir = None
    if args.output:
        output_dir = Path(args.output)
        output_dir.mkdir(parents=True, exist_ok=True)

    engine = SignalResponseBenchmark(DB_PATH)

    for name, config in to_run.items():
        config.bootstrap_iterations = args.bootstrap

        print(f"\n{'#' * 78}")
        print(f"# BENCHMARK: {name}")
        print(f"{'#' * 78}\n")

        results = engine.run(config)
        print_report(results)

        if output_dir:
            out_path = output_dir / f"benchmark_{name}.json"
            results.to_json(out_path)
            print(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    main()
