"""
save_results.py
---------------
Called by Jenkins after each backtest run.

  1. Finds the most recently produced trade-records CSV under
     results/backtest_results/ (or the folder matching the strategy name).
  2. Computes performance metrics (same logic as generate_metrics_report.py).
  3. Persists one row per run into a SQLite database for trend tracking.
  4. Writes the metrics as a JSON file for archiving.

Usage:
    python scripts/save_results.py \
        --config    trading_v2/configs/backtest_smoke.yaml \
        --metrics-file trading_v2/configs/backtest_config_metrics.json \
        --db        /path/to/backtest_results.db \
        --build     42
"""

import argparse
import json
import math
import os
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd
import yaml

from trading.utils.logger import info

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR  = PROJECT_ROOT / "results" / "backtest_results"

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--config",       required=True,  help="Path to the YAML config that was run")
    p.add_argument("--metrics-file", required=True,  help="Where to write the metrics JSON")
    p.add_argument("--db",           required=False, help="Path to SQLite DB (default: backtest_results.db next to this script)")
    p.add_argument("--build",        required=False, default="", help="Jenkins build number")
    return p.parse_args()

# ---------------------------------------------------------------------------
# SQLite helpers
# ---------------------------------------------------------------------------
CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS runs (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    build_number          TEXT,
    timestamp             TEXT,
    strategy              TEXT,
    config_file           TEXT,
    timeframe             TEXT,
    symbols               TEXT,
    n_trades              INTEGER,
    win_rate_pct          REAL,
    total_pnl             REAL,
    avg_pnl_per_trade     REAL,
    avg_win               REAL,
    avg_loss              REAL,
    profit_factor         REAL,
    max_drawdown          REAL,
    pd_ratio              REAL,
    sharpe_ratio          REAL,
    max_consecutive_losses INTEGER,
    metrics_json          TEXT
);
"""

def get_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute(CREATE_TABLE)
    conn.commit()
    return conn

# ---------------------------------------------------------------------------
# Find latest CSVs
# ---------------------------------------------------------------------------
def find_latest_csvs(strategy_name: str | None) -> list[Path]:
    """Return CSVs from the most recently modified strategy sub-folder."""
    if strategy_name:
        folder = RESULTS_DIR / strategy_name
        if folder.exists():
            csvs = sorted(folder.glob("trade_records_*.csv"), key=lambda p: p.stat().st_mtime)
            if csvs:
                return csvs

    # Fall back: search everywhere
    csvs = sorted(RESULTS_DIR.rglob("trade_records_*.csv"), key=lambda p: p.stat().st_mtime)
    if not csvs:
        csvs = sorted(RESULTS_DIR.rglob("trade_records*.csv"), key=lambda p: p.stat().st_mtime)
    if not csvs:
        raise FileNotFoundError(f"No trade-record CSVs found under {RESULTS_DIR}")

    latest_folder = csvs[-1].parent
    return [p for p in csvs if p.parent == latest_folder]

# ---------------------------------------------------------------------------
# Load + filter trades
# ---------------------------------------------------------------------------
def load_trades(csv_paths: list[Path]) -> pd.DataFrame:
    frames = [pd.read_csv(p) for p in csv_paths]
    df = pd.concat(frames, ignore_index=True)

    for col in ("datetime", "entry_date", "exit_date"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")

    if "closed" in df.columns and "cancelled" in df.columns:
        df = df[df["closed"].astype(str).str.lower() == "true"]
        df = df[df["cancelled"].astype(str).str.lower() == "false"]

    return df.sort_values("datetime").reset_index(drop=True)

# ---------------------------------------------------------------------------
# Compute metrics
# ---------------------------------------------------------------------------
def compute_metrics(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"error": "No closed trades found."}

    profits  = df["profit"].dropna().astype(float)
    n_trades = len(profits)
    wins     = profits[profits > 0]
    losses   = profits[profits <= 0]

    win_rate      = round(len(wins) / n_trades * 100, 2)   if n_trades else 0.0
    total_pnl     = round(float(profits.sum()), 6)
    avg_pnl       = round(float(profits.mean()), 6)
    avg_win       = round(float(wins.mean()), 6)            if len(wins)   else 0.0
    avg_loss      = round(float(losses.mean()), 6)          if len(losses) else 0.0
    profit_factor = round(abs(wins.sum() / losses.sum()), 4) if losses.sum() != 0 else float("inf")

    cum_pnl  = profits.cumsum().reset_index(drop=True)
    roll_max = cum_pnl.cummax()
    max_dd   = round(float((roll_max - cum_pnl).max()), 6)
    pd_ratio = round(total_pnl / max_dd, 4) if max_dd != 0 else (float("nan") if total_pnl > 0 else 0.0)

    sharpe = float("nan")
    if "datetime" in df.columns:
        daily = df.groupby(df["datetime"].dt.date)["profit"].sum()
        if len(daily) > 1:
            mu, sigma = daily.mean(), daily.std(ddof=1)
            if sigma and sigma > 0:
                sharpe = round(float(mu / sigma * math.sqrt(252)), 4)

    max_consec = cur = 0
    for p in profits:
        cur = cur + 1 if p <= 0 else 0
        max_consec = max(max_consec, cur)

    return {
        "generated_at":          datetime.now().isoformat(timespec="seconds"),
        "n_trades":               n_trades,
        "win_rate_pct":           win_rate,
        "total_pnl":              total_pnl,
        "avg_pnl_per_trade":      avg_pnl,
        "avg_win":                avg_win,
        "avg_loss":               avg_loss,
        "profit_factor":          profit_factor,
        "max_drawdown":           max_dd,
        "pd_ratio":               pd_ratio,
        "sharpe_ratio":           sharpe,
        "max_consecutive_losses": max_consec,
    }

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    args = parse_args()

    # Resolve DB path
    db_path = args.db or str(PROJECT_ROOT / "backtest_results.db")
    info(f"Using DB: {db_path}")

    # Load config to extract metadata
    config_path = Path(args.config)
    strategy, timeframe, symbols = "unknown", "unknown", ""
    if config_path.exists():
        with open(config_path) as f:
            cfg = yaml.safe_load(f) or {}
        strategy  = cfg.get("strategy",  "unknown")
        timeframe = cfg.get("timeframe", "unknown")
        symbols   = ", ".join(cfg.get("symbols", []))

    # Find and load trades
    csv_paths = find_latest_csvs(strategy if strategy != "unknown" else None)
    info(f"Found {len(csv_paths)} CSV(s) from: {csv_paths[0].parent}")
    df = load_trades(csv_paths)
    info(f"Loaded {len(df)} closed trades.")

    # Compute metrics
    metrics = compute_metrics(df)
    metrics["strategy"]   = strategy
    metrics["timeframe"]  = timeframe
    metrics["symbols"]    = symbols
    metrics["config_file"] = str(config_path)

    # Write metrics JSON
    metrics_path = Path(args.metrics_file)
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_path.write_text(json.dumps(metrics, indent=2, default=str), encoding="utf-8")
    info(f"Metrics JSON written to: {metrics_path}")

    # Persist to SQLite
    conn = get_db(db_path)
    conn.execute("""
        INSERT INTO runs (
            build_number, timestamp, strategy, config_file, timeframe, symbols,
            n_trades, win_rate_pct, total_pnl, avg_pnl_per_trade, avg_win, avg_loss,
            profit_factor, max_drawdown, pd_ratio, sharpe_ratio, max_consecutive_losses,
            metrics_json
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        str(args.build),
        metrics["generated_at"],
        strategy,
        str(config_path),
        timeframe,
        symbols,
        metrics.get("n_trades"),
        metrics.get("win_rate_pct"),
        metrics.get("total_pnl"),
        metrics.get("avg_pnl_per_trade"),
        metrics.get("avg_win"),
        metrics.get("avg_loss"),
        metrics.get("profit_factor") if not math.isinf(metrics.get("profit_factor", 0)) else None,
        metrics.get("max_drawdown"),
        metrics.get("pd_ratio") if not (isinstance(metrics.get("pd_ratio"), float) and math.isnan(metrics.get("pd_ratio"))) else None,
        metrics.get("sharpe_ratio") if not (isinstance(metrics.get("sharpe_ratio"), float) and math.isnan(metrics.get("sharpe_ratio"))) else None,
        metrics.get("max_consecutive_losses"),
        json.dumps(metrics, default=str),
    ))
    conn.commit()
    conn.close()
    info(f"Results saved to SQLite (build #{args.build})")

    # info summary
    info("\n========== METRICS SUMMARY ==========")
    for k, v in metrics.items():
        if k != "metrics_json":
            info(f"  {k:<30} {v}")
    info("=====================================\n")


if __name__ == "__main__":
    main()
