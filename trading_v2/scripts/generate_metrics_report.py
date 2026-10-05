"""
generate_metrics_report.py

Thin CLI around trading.backtesting.metrics_report.generate_report().

You normally don't need to run this directly — scripts/run_backtest.py calls
it automatically at the end of every backtest run, writing metrics.json +
report.html + figures/ straight into that run's own results folder.

Use this script to regenerate a report for an existing run (e.g. after
changing the report logic) without re-running the backtest itself.

Usage:
    python scripts/generate_metrics_report.py --run-dir results/momentum_v1.3/20260820_143201
    python scripts/generate_metrics_report.py --latest
    python scripts/generate_metrics_report.py --latest --strategy momentum_v1.3
"""

import argparse
from pathlib import Path

from trading.utils import constants
from trading.utils.logger import info, warning, error
from trading.backtesting.metrics_report import generate_report


def find_latest_run_dir(strategy: str | None = None) -> Path:
    """Most recently modified run folder (the one containing trades.csv),
    optionally restricted to a single strategy's subfolder."""
    results_dir = Path(constants.RESULTS_DIR)
    if strategy:
        results_dir = results_dir / strategy

    info(f"Searching for the most recently modified run under {results_dir}")
    trade_files = list(results_dir.rglob("trades.csv"))
    if not trade_files:
        error(f"No run folders (containing trades.csv) found under {results_dir}", __file__)
        raise FileNotFoundError(f"No run folders (containing trades.csv) found under {results_dir}")

    latest = max(trade_files, key=lambda p: p.stat().st_mtime).parent
    info(f"Latest run found: {latest}")
    return latest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", help="Path to a specific run folder (containing trades.csv)")
    parser.add_argument("--latest", action="store_true", help="Use the most recently modified run folder")
    parser.add_argument("--strategy", help="Restrict --latest to a specific strategy subfolder")
    args = parser.parse_args()

    if args.run_dir:
        run_dir = Path(args.run_dir)
    elif args.latest:
        run_dir = find_latest_run_dir(args.strategy)
    else:
        warning("No --run-dir or --latest given — nothing to do.", __file__)
        parser.error("Specify either --run-dir <path> or --latest")
        return

    info(f"Generating report for: {run_dir}")
    generate_report(run_dir)
    info("Done.")


if __name__ == "__main__":
    main()
