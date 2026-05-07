"""
generate_metrics_report.py

Finds the most recently produced trade-records CSV(s) under
results/backtest_results/, computes performance metrics, and writes:
  - results/reports/metrics_<timestamp>.json   (machine-readable)
  - results/reports/performance_report.html    (Jenkins HTML Publisher)

Run standalone:
    python scripts/generate_metrics_report.py
"""

import os
import sys
import json
import math
import base64
import io
from datetime import datetime
from pathlib import Path

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")          # headless – no display needed
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR  = PROJECT_ROOT / "results" / "backtest_results"
REPORTS_DIR  = PROJECT_ROOT / "results" / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# 1. Find the latest trade-records CSV
# ---------------------------------------------------------------------------
def find_latest_csv(results_dir: Path) -> Path:
    """Return the single most recently modified trade-records CSV."""
    csvs = sorted(
        results_dir.rglob("trade_records_*.csv"),
        key=lambda p: p.stat().st_mtime,
    )
    if not csvs:
        # Fallback to the loose pattern, just in case naming drifts
        csvs = sorted(
            results_dir.rglob("trade_records*.csv"),
            key=lambda p: p.stat().st_mtime,
        )
    if not csvs:
        print("No trade-record CSVs found under", results_dir)
        sys.exit(1)

    latest = csvs[-1]
    print(f"Using latest CSV: {latest}")
    return latest


# ---------------------------------------------------------------------------
# 2. Load and merge CSVs
# ---------------------------------------------------------------------------
def load_trades(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path)

    # Parse date columns
    for col in ("datetime", "entry_date", "exit_date"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")

    # Keep only closed (non-cancelled) trades for metrics
    if "closed" in df.columns and "cancelled" in df.columns:
        df = df[df["closed"].astype(str).str.lower() == "true"]
        df = df[df["cancelled"].astype(str).str.lower() == "false"]

    return df.sort_values("datetime").reset_index(drop=True)


# ---------------------------------------------------------------------------
# 3. Compute metrics
# ---------------------------------------------------------------------------
def compute_metrics(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"error": "No closed trades found after filtering."}

    profits = df["profit"].dropna().astype(float)
    n_trades = len(profits)

    # Win / loss
    wins  = profits[profits > 0]
    losses = profits[profits <= 0]
    win_rate = round(len(wins) / n_trades * 100, 2) if n_trades else 0.0

    total_pnl     = round(float(profits.sum()), 6)
    avg_pnl       = round(float(profits.mean()), 6)
    avg_win       = round(float(wins.mean()), 6)   if len(wins)   else 0.0
    avg_loss      = round(float(losses.mean()), 6) if len(losses) else 0.0
    profit_factor = round(abs(wins.sum() / losses.sum()), 4) if losses.sum() != 0 else float("inf")

    # Cumulative PnL series
    cum_pnl = profits.cumsum().reset_index(drop=True)

    # Max drawdown (in PnL units)
    roll_max = cum_pnl.cummax()
    drawdown = roll_max - cum_pnl
    max_dd   = round(float(drawdown.max()), 6)

    # PD ratio (same definition as strategy_results.py)
    pd_ratio = round(total_pnl / max_dd, 4) if max_dd != 0 else (float("nan") if total_pnl > 0 else 0.0)

    # Sharpe ratio – group by day, compute daily PnL, annualise
    sharpe = float("nan")
    if "datetime" in df.columns:
        daily = df.groupby(df["datetime"].dt.date)["profit"].sum()
        if len(daily) > 1:
            mu    = daily.mean()
            sigma = daily.std(ddof=1)
            if sigma and sigma > 0:
                # Annualise: √252 for daily, √(252*24) if intraday — use 252 as default
                sharpe = round(float(mu / sigma * math.sqrt(252)), 4)

    # Max consecutive losses
    max_consec_loss = 0
    cur = 0
    for p in profits:
        if p <= 0:
            cur += 1
            max_consec_loss = max(max_consec_loss, cur)
        else:
            cur = 0

    # Trade-type breakdown
    trade_type_counts = {}
    if "trade_type" in df.columns:
        trade_type_counts = df["trade_type"].value_counts().to_dict()

    # Close reason breakdown
    close_reason_counts = {}
    if "pending_close_reason" in df.columns:
        close_reason_counts = df["pending_close_reason"].value_counts().to_dict()

    # Asset breakdown
    asset_pnl = {}
    if "asset" in df.columns:
        asset_pnl = df.groupby("asset")["profit"].sum().round(6).to_dict()

    return {
        "generated_at":         datetime.now().isoformat(timespec="seconds"),
        "n_trades":              n_trades,
        "win_rate_pct":          win_rate,
        "total_pnl":             total_pnl,
        "avg_pnl_per_trade":     avg_pnl,
        "avg_win":               avg_win,
        "avg_loss":              avg_loss,
        "profit_factor":         profit_factor,
        "max_drawdown":          max_dd,
        "pd_ratio":              pd_ratio,
        "sharpe_ratio":          sharpe,
        "max_consecutive_losses":max_consec_loss,
        "trade_type_breakdown":  trade_type_counts,
        "close_reason_breakdown":close_reason_counts,
        "asset_pnl":             asset_pnl,
    }


# ---------------------------------------------------------------------------
# 4. Build charts (returns base64-encoded PNG strings)
# ---------------------------------------------------------------------------
def _fig_to_b64(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("utf-8")


def build_charts(df: pd.DataFrame) -> dict[str, str]:
    charts = {}
    profits = df["profit"].astype(float)
    cum_pnl = profits.cumsum().reset_index(drop=True)

    # --- Equity curve ---
    fig, ax = plt.subplots(figsize=(10, 4))
    if "datetime" in df.columns:
        ax.plot(df["datetime"].values, cum_pnl.values, linewidth=1.2, color="#1f77b4")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
        fig.autofmt_xdate()
    else:
        ax.plot(cum_pnl.values, linewidth=1.2, color="#1f77b4")
        ax.set_xlabel("Trade #")
    ax.axhline(0, color="red", linestyle="--", linewidth=0.8)
    ax.set_title("Cumulative PnL (Equity Curve)")
    ax.set_ylabel("PnL")
    ax.grid(True, alpha=0.3)
    charts["equity_curve"] = _fig_to_b64(fig)
    plt.close(fig)

    # --- Drawdown curve ---
    roll_max = cum_pnl.cummax()
    drawdown = roll_max - cum_pnl
    fig, ax = plt.subplots(figsize=(10, 3))
    if "datetime" in df.columns:
        ax.fill_between(df["datetime"].values, -drawdown.values, 0, color="crimson", alpha=0.5)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
        fig.autofmt_xdate()
    else:
        ax.fill_between(range(len(drawdown)), -drawdown.values, 0, color="crimson", alpha=0.5)
        ax.set_xlabel("Trade #")
    ax.set_title("Drawdown")
    ax.set_ylabel("Drawdown")
    ax.grid(True, alpha=0.3)
    charts["drawdown"] = _fig_to_b64(fig)
    plt.close(fig)

    # --- PnL distribution ---
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.hist(profits.values, bins=40, color="#2ca02c", edgecolor="white", linewidth=0.4)
    ax.axvline(0, color="red", linestyle="--", linewidth=0.8)
    ax.set_title("Trade PnL Distribution")
    ax.set_xlabel("PnL per Trade")
    ax.set_ylabel("Frequency")
    ax.grid(True, alpha=0.3)
    charts["pnl_dist"] = _fig_to_b64(fig)
    plt.close(fig)

    return charts


# ---------------------------------------------------------------------------
# 5. Write HTML report
# ---------------------------------------------------------------------------
def _metric_row(label, value, good=None) -> str:
    """Colour a row green/red depending on whether the value is 'good'."""
    if good is True:
        colour = "#d4edda"
    elif good is False:
        colour = "#f8d7da"
    else:
        colour = "#ffffff"
    return f'<tr style="background:{colour}"><td>{label}</td><td><strong>{value}</strong></td></tr>'


def write_html(metrics: dict, charts: dict, out_path: Path, csv_path: Path):
    nan_str = lambda v: "N/A" if (isinstance(v, float) and math.isnan(v)) else str(v)

    win_good     = metrics.get("win_rate_pct", 0) >= 50
    pf_good      = metrics.get("profit_factor", 0) >= 1.5
    sharpe_good  = (not isinstance(metrics.get("sharpe_ratio"), float)
                    or not math.isnan(metrics.get("sharpe_ratio", float("nan"))))  \
                   and metrics.get("sharpe_ratio", 0) >= 1.0
    pnl_good     = metrics.get("total_pnl", 0) > 0

    rows = "".join([
        _metric_row("Total Trades",            metrics.get("n_trades", "—")),
        _metric_row("Win Rate",                f'{metrics.get("win_rate_pct","—")}%',        good=win_good),
        _metric_row("Total PnL",               nan_str(metrics.get("total_pnl", float("nan"))), good=pnl_good),
        _metric_row("Avg PnL / Trade",         nan_str(metrics.get("avg_pnl_per_trade", float("nan")))),
        _metric_row("Avg Win",                 nan_str(metrics.get("avg_win", float("nan")))),
        _metric_row("Avg Loss",                nan_str(metrics.get("avg_loss", float("nan")))),
        _metric_row("Profit Factor",           nan_str(metrics.get("profit_factor", float("nan"))), good=pf_good),
        _metric_row("Max Drawdown",            nan_str(metrics.get("max_drawdown", float("nan")))),
        _metric_row("PD Ratio",                nan_str(metrics.get("pd_ratio", float("nan")))),
        _metric_row("Sharpe Ratio (ann.)",     nan_str(metrics.get("sharpe_ratio", float("nan"))), good=sharpe_good),
        _metric_row("Max Consecutive Losses",  metrics.get("max_consecutive_losses", "—")),
    ])

    # Breakdown tables
    def breakdown_table(d: dict, header: str) -> str:
        if not d:
            return ""
        inner = "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in d.items())
        return f"""
        <h3>{header}</h3>
        <table><thead><tr><th>Category</th><th>Count / PnL</th></tr></thead>
        <tbody>{inner}</tbody></table>"""

    breakdown_html = (
        breakdown_table(metrics.get("trade_type_breakdown", {}),  "Trade Type Breakdown")
        + breakdown_table(metrics.get("close_reason_breakdown", {}), "Close Reason Breakdown")
        + breakdown_table(metrics.get("asset_pnl", {}),             "PnL by Asset")
    )

    # Chart tags
    chart_tags = ""
    for title, key in [("Equity Curve", "equity_curve"),
                       ("Drawdown",     "drawdown"),
                       ("PnL Distribution", "pnl_dist")]:
        if key in charts:
            chart_tags += f"""
            <h3>{title}</h3>
            <img src="data:image/png;base64,{charts[key]}" style="max-width:100%;margin-bottom:24px;">"""

    sources = str(csv_path)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Backtest Performance Report</title>
  <style>
    body  {{ font-family: Arial, sans-serif; max-width: 960px; margin: 40px auto; color: #333; }}
    h1   {{ color: #1a1a2e; border-bottom: 2px solid #1f77b4; padding-bottom: 8px; }}
    h2   {{ color: #16213e; margin-top: 32px; }}
    h3   {{ color: #444; margin-top: 24px; }}
    table{{ border-collapse: collapse; width: 100%; margin-bottom: 16px; }}
    th,td{{ border: 1px solid #ddd; padding: 8px 14px; text-align: left; }}
    th   {{ background: #1f77b4; color: white; }}
    .meta{{ font-size: 0.85em; color: #777; margin-bottom: 24px; }}
    .pass{{ color: green; font-weight: bold; }}
    .fail{{ color: red;   font-weight: bold; }}
  </style>
</head>
<body>
  <h1>Backtest Performance Report</h1>
  <p class="meta">
    Generated: {metrics.get("generated_at", "—")}<br>
    Source files:<br><code>{sources}</code>
  </p>

  <h2>Summary Metrics</h2>
  <table>
    <thead><tr><th>Metric</th><th>Value</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>

  {breakdown_html}

  <h2>Charts</h2>
  {chart_tags}

</body>
</html>"""

    out_path.write_text(html, encoding="utf-8")
    print(f"HTML report written to: {out_path}")


# ---------------------------------------------------------------------------
# 6. Main
# ---------------------------------------------------------------------------
def generate_metrics_reportmain():
    csv_path = find_latest_csv(RESULTS_DIR)
    df = load_trades(csv_path)

    print(f"Loaded {len(df)} closed trades.")

    metrics = compute_metrics(df)
    charts  = build_charts(df) if not df.empty else {}

    # Write JSON
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    json_path = REPORTS_DIR / "JSON" / datetime.now().strftime('%Y%m%d') / f"metrics_{timestamp}.json"
    html_path = REPORTS_DIR / "HTML" / datetime.now().strftime('%Y%m%d') / "performance_report.html"

    json_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.parent.mkdir(parents=True, exist_ok=True)

    json_path.write_text(json.dumps(metrics, indent=2, default=str), encoding="utf-8")
    print(f"JSON metrics written to: {json_path}")

    write_html(metrics, charts, html_path, csv_path)

    # Print summary to stdout so it shows in Jenkins console
    print("\n========== PERFORMANCE SUMMARY ==========")
    for k, v in metrics.items():
        if not isinstance(v, dict):
            print(f"  {k:<30} {v}")
    print("=========================================\n")


if __name__ == "__main__":
    generate_metrics_reportmain()
