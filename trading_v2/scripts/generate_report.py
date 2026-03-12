"""
generate_report.py
------------------
Reads the last N backtest runs from the SQLite database and generates a
self-contained HTML report with a results table and trend charts.

Usage:
    python scripts/generate_report.py \
        --output  trading_v2/reports/report.html \
        --last    20 \
        --db      /path/to/backtest_results.db
"""

import argparse
import base64
import io
import json
import math
import os
import sqlite3
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import pandas as pd

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--output", required=True,  help="Path for the output HTML file")
    p.add_argument("--last",   type=int, default=20, help="Number of most recent runs to include")
    p.add_argument("--db",     required=False,  help="Path to SQLite DB")
    return p.parse_args()

# ---------------------------------------------------------------------------
# Load runs from SQLite
# ---------------------------------------------------------------------------
def load_runs(db_path: str, last_n: int) -> pd.DataFrame:
    if not Path(db_path).exists():
        raise FileNotFoundError(f"Database not found: {db_path}")
    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query(
        f"SELECT * FROM runs ORDER BY id DESC LIMIT {last_n}",
        conn
    )
    conn.close()
    return df.iloc[::-1].reset_index(drop=True)   # oldest → newest for charting

# ---------------------------------------------------------------------------
# Chart helpers
# ---------------------------------------------------------------------------
def _fig_to_b64(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("utf-8")


def chart_trend(df: pd.DataFrame, col: str, title: str, colour: str, zero_line=False) -> str:
    if col not in df.columns or df[col].dropna().empty:
        return ""
    fig, ax = plt.subplots(figsize=(10, 3))
    x = range(len(df))
    vals = pd.to_numeric(df[col], errors="coerce")
    ax.plot(list(x), vals.tolist(), marker="o", markersize=4, linewidth=1.5, color=colour)
    ax.fill_between(list(x), vals.tolist(), alpha=0.15, color=colour)
    if zero_line:
        ax.axhline(0, color="red", linestyle="--", linewidth=0.8)
    labels = df["build_number"].tolist() if "build_number" in df.columns else [str(i) for i in x]
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
    ax.set_title(title, fontsize=11)
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    b64 = _fig_to_b64(fig)
    plt.close(fig)
    return f'<img src="data:image/png;base64,{b64}" style="max-width:100%;margin-bottom:8px;">'


def chart_win_rate(df: pd.DataFrame) -> str:
    if "win_rate_pct" not in df.columns:
        return ""
    fig, ax = plt.subplots(figsize=(10, 3))
    x = range(len(df))
    vals = pd.to_numeric(df["win_rate_pct"], errors="coerce")
    colours = ["#2ca02c" if v >= 50 else "#d62728" for v in vals]
    ax.bar(list(x), vals.tolist(), color=colours, alpha=0.8)
    ax.axhline(50, color="black", linestyle="--", linewidth=0.8)
    labels = df["build_number"].tolist() if "build_number" in df.columns else [str(i) for i in x]
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
    ax.yaxis.set_major_formatter(mticker.PercentFormatter())
    ax.set_title("Win Rate per Build", fontsize=11)
    ax.grid(True, alpha=0.3, axis="y")
    plt.tight_layout()
    b64 = _fig_to_b64(fig)
    plt.close(fig)
    return f'<img src="data:image/png;base64,{b64}" style="max-width:100%;margin-bottom:8px;">'

# ---------------------------------------------------------------------------
# Table helpers
# ---------------------------------------------------------------------------
def _cell(val, good_thresh=None, bad_thresh=None, fmt=None, pct=False) -> str:
    """Render a <td> coloured green/red based on optional thresholds."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return "<td>—</td>"
    display = f"{val:.4f}" if fmt == "f" else (f"{val:.2f}%" if pct else str(val))
    colour = ""
    try:
        v = float(val)
        if good_thresh is not None and v >= good_thresh:
            colour = "background:#d4edda;"
        elif bad_thresh is not None and v <= bad_thresh:
            colour = "background:#f8d7da;"
    except (TypeError, ValueError):
        pass
    return f'<td style="{colour}">{display}</td>'


def build_table(df: pd.DataFrame) -> str:
    headers = ["Build", "Timestamp", "Strategy", "TF", "Symbols",
               "Trades", "Win Rate", "Total PnL", "Avg PnL", "Profit Factor",
               "Max DD", "PD Ratio", "Sharpe"]
    rows_html = ""
    for _, row in df.iterrows():
        rows_html += "<tr>"
        rows_html += f"<td>{row.get('build_number','—')}</td>"
        rows_html += f"<td style='white-space:nowrap'>{str(row.get('timestamp',''))[:19]}</td>"
        rows_html += f"<td>{row.get('strategy','—')}</td>"
        rows_html += f"<td>{row.get('timeframe','—')}</td>"
        rows_html += f"<td>{row.get('symbols','—')}</td>"
        rows_html += f"<td>{row.get('n_trades','—')}</td>"
        rows_html += _cell(row.get("win_rate_pct"), good_thresh=55, bad_thresh=45, pct=True)
        rows_html += _cell(row.get("total_pnl"),    good_thresh=0,  bad_thresh=None, fmt="f")
        rows_html += _cell(row.get("avg_pnl_per_trade"), fmt="f")
        rows_html += _cell(row.get("profit_factor"), good_thresh=1.5, bad_thresh=1.0, fmt="f")
        rows_html += _cell(row.get("max_drawdown"), fmt="f")
        rows_html += _cell(row.get("pd_ratio"),     good_thresh=2.0, bad_thresh=1.0, fmt="f")
        rows_html += _cell(row.get("sharpe_ratio"), good_thresh=1.0, bad_thresh=0.5, fmt="f")
        rows_html += "</tr>"

    header_html = "".join(f"<th>{h}</th>" for h in headers)
    return f"""
    <div style="overflow-x:auto;">
    <table>
        <thead><tr>{header_html}</tr></thead>
        <tbody>{rows_html}</tbody>
    </table>
    </div>"""

# ---------------------------------------------------------------------------
# Write HTML
# ---------------------------------------------------------------------------
def write_html(df: pd.DataFrame, out_path: Path, last_n: int):
    out_path.parent.mkdir(parents=True, exist_ok=True)

    table_html  = build_table(df)
    chart_pnl   = chart_trend(df, "total_pnl",     "Total PnL per Build",         "#1f77b4", zero_line=True)
    chart_sharpe= chart_trend(df, "sharpe_ratio",   "Sharpe Ratio per Build",      "#9467bd", zero_line=True)
    chart_dd    = chart_trend(df, "max_drawdown",   "Max Drawdown per Build",      "#d62728")
    chart_wr    = chart_win_rate(df)
    chart_pf    = chart_trend(df, "profit_factor",  "Profit Factor per Build",     "#2ca02c")

    generated   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total_runs  = len(df)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Backtest Report</title>
  <style>
    body  {{ font-family: Arial, sans-serif; max-width: 1200px; margin: 40px auto; color: #333; padding: 0 16px; }}
    h1   {{ color: #1a1a2e; border-bottom: 3px solid #1f77b4; padding-bottom: 8px; }}
    h2   {{ color: #16213e; margin-top: 36px; border-left: 4px solid #1f77b4; padding-left: 10px; }}
    table{{ border-collapse: collapse; width: 100%; font-size: 0.88em; }}
    th,td{{ border: 1px solid #ddd; padding: 7px 12px; text-align: left; }}
    th   {{ background: #1f77b4; color: white; position: sticky; top: 0; }}
    tr:nth-child(even) {{ background: #f9f9f9; }}
    .meta {{ font-size: 0.82em; color: #777; margin-bottom: 24px; }}
    .charts {{ display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }}
    @media (max-width: 800px) {{ .charts {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <h1>Backtest Performance Report</h1>
  <p class="meta">Generated: {generated} &nbsp;|&nbsp; Showing last {total_runs} build(s)</p>

  <h2>Results Table</h2>
  {table_html}

  <h2>Trend Charts</h2>
  <div class="charts">
    <div>{chart_pnl}</div>
    <div>{chart_wr}</div>
    <div>{chart_sharpe}</div>
    <div>{chart_pf}</div>
    <div>{chart_dd}</div>
  </div>

</body>
</html>"""

    out_path.write_text(html, encoding="utf-8")
    print(f"Report written to: {out_path}")

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    args = parse_args()

    PROJECT_ROOT = Path(__file__).resolve().parents[1]
    db_path = args.db or str(PROJECT_ROOT / "backtest_results.db")

    print(f"Reading from DB: {db_path}")
    df = load_runs(db_path, args.last)
    print(f"Loaded {len(df)} run(s).")

    if df.empty:
        print("No runs found in database — nothing to report.")
        return

    write_html(df, Path(args.output), args.last)


if __name__ == "__main__":
    main()
