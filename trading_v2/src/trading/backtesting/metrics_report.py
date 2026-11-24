"""
metrics_report.py

Computes a full performance report from a single backtest run's trade
records and writes everything into that run's own folder:

    results/<strategy>/<run_id>/
        trades.csv        (already written by run_backtest.py)
        config.yaml        (already written by run_backtest.py)
        metrics.json           <- written by this module
        report.html                <- written by this module
        figures/
            equity_curve.png           <- written by this module
            drawdown.png
            pnl_distribution.png
            equity_by_asset.png

Called automatically by scripts/run_backtest.py at the end of every run.
Can also be re-run standalone via scripts/generate_metrics_report.py to
regenerate a report for an existing run without re-running the backtest.
"""

import base64
import io
import json
import math
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # headless — no display needed
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

from trading.utils.logger import info, warning, error

# ---------------------------------------------------------------------------
# 1. Load + split trades
# ---------------------------------------------------------------------------

_BOOL_COLS = ("open", "closed", "cancelled", "pending_close", "is_limit")
_DATE_COLS = ("datetime", "entry_date", "exit_date")


def _coerce_bool(series: pd.Series) -> pd.Series:
    if series.dtype == bool:
        return series
    return (
        series.astype(str)
        .str.strip()
        .str.lower()
        .map({"true": True, "false": False})
    )


def load_trades_raw(csv_path) -> pd.DataFrame:
    """Load a run's trades.csv exactly as produced, all statuses included."""
    info(f"Loading trade records from {csv_path}")
    try:
        df = pd.read_csv(csv_path)
    except FileNotFoundError:
        error(f"trades.csv not found at {csv_path}", __file__)
        raise
    except Exception as e:
        error(f"Failed to parse {csv_path}: {e}", __file__)
        raise

    for col in _DATE_COLS:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")

    for col in _BOOL_COLS:
        if col in df.columns:
            df[col] = _coerce_bool(df[col])

    if df.empty:
        warning(f"trades.csv at {csv_path} has no rows.", __file__)
    else:
        info(f"Loaded {len(df)} trade record(s) with {df.shape[1]} columns")

    return df


def closed_trades(df: pd.DataFrame) -> pd.DataFrame:
    """Trades that actually closed (excludes still-open and cancelled),
    sorted by exit_date since that's when profit is realised."""
    if df.empty:
        warning("No trade records to filter for closed trades.", __file__)
        return df
    mask = pd.Series(True, index=df.index)
    if "closed" in df.columns:
        mask &= df["closed"] == True  # noqa: E712
    if "cancelled" in df.columns:
        mask &= df["cancelled"] == False  # noqa: E712
    out = df[mask].copy()
    if "exit_date" in out.columns:
        out = out.sort_values("exit_date")
    out = out.reset_index(drop=True)

    if out.empty:
        warning(f"None of the {len(df)} trade(s) in this run are closed — performance metrics will be empty.", __file__)
    else:
        info(f"{len(out)} of {len(df)} trades are closed (excludes open/cancelled)")

    return out


# ---------------------------------------------------------------------------
# 2. Metrics
# ---------------------------------------------------------------------------

def compute_coverage(df: pd.DataFrame) -> dict:
    """What data this run actually traded on: date range, assets, timeframes."""
    coverage = {}
    if "entry_date" in df.columns and df["entry_date"].notna().any():
        coverage["data_start"] = df["entry_date"].min().date().isoformat()
    if "exit_date" in df.columns and df["exit_date"].notna().any():
        coverage["data_end"] = df["exit_date"].max().date().isoformat()
    if "asset" in df.columns:
        coverage["assets"] = sorted(df["asset"].dropna().unique().tolist())
    if "time_frame" in df.columns:
        coverage["timeframes"] = sorted(df["time_frame"].dropna().unique().tolist())
    info(f"Coverage: {coverage.get('data_start', '?')} -> {coverage.get('data_end', '?')}, "
         f"assets={coverage.get('assets', [])}, timeframes={coverage.get('timeframes', [])}")
    return coverage


def compute_status_counts(df: pd.DataFrame) -> dict:
    """How many trades ended up in each state — open/closed/cancelled — plus
    why trades closed (take_profit / stop_loss / max_hold), across ALL trades
    that ever had a pending_close_reason recorded, not just currently-open ones."""
    counts = {"total_trades": int(len(df))}
    for col in ("open", "closed", "cancelled"):
        if col in df.columns:
            counts[col] = int((df[col] == True).sum())  # noqa: E712
    if "pending_close_reason" in df.columns:
        reasons = df["pending_close_reason"].dropna()
        reasons = reasons[reasons.astype(str).str.len() > 0]
        if len(reasons):
            counts["close_reason_breakdown"] = reasons.value_counts().to_dict()
    info(f"Status counts: {counts}")
    return counts


def compute_performance_metrics(closed_df: pd.DataFrame) -> dict:
    if closed_df.empty or "profit" not in closed_df.columns:
        warning("No closed trades available — skipping performance metrics.", __file__)
        return {"error": "No closed trades to compute performance metrics from."}

    profits = closed_df["profit"].dropna().astype(float)
    n = len(profits)
    if n == 0:
        warning("Closed trades exist but none have a recorded profit value.", __file__)
        return {"error": "No closed trades with a recorded profit."}

    wins = profits[profits > 0]
    losses = profits[profits <= 0]

    gross_profit = round(float(wins.sum()), 6)
    gross_loss = round(float(losses.sum()), 6)
    profit_factor = (
        round(abs(gross_profit / gross_loss), 4) if gross_loss != 0
        else (float("inf") if gross_profit > 0 else 0.0)
    )

    cum_pnl = profits.cumsum().reset_index(drop=True)
    roll_max = cum_pnl.cummax()
    drawdown = roll_max - cum_pnl
    max_dd = round(float(drawdown.max()), 6)
    total_pnl = round(float(profits.sum()), 6)
    pd_ratio = (
        round(total_pnl / max_dd, 4) if max_dd != 0
        else (float("nan") if total_pnl > 0 else 0.0)
    )

    sharpe = float("nan")
    if "exit_date" in closed_df.columns:
        dated = closed_df.dropna(subset=["exit_date"])
        if len(dated):
            daily = dated.groupby(dated["exit_date"].dt.date)["profit"].sum()
            if len(daily) > 1:
                mu, sigma = daily.mean(), daily.std(ddof=1)
                if sigma and sigma > 0:
                    sharpe = round(float(mu / sigma * math.sqrt(252)), 4)

    max_consec_loss = cur = 0
    for p in profits:
        cur = cur + 1 if p <= 0 else 0
        max_consec_loss = max(max_consec_loss, cur)

    if math.isnan(sharpe):
        warning("Sharpe ratio could not be computed (need exit_date on more than one distinct day).", __file__)

    win_rate_pct = round(len(wins) / n * 100, 2)
    info(f"Performance over {n} closed trades: win_rate={win_rate_pct}%, "
         f"total_pnl={total_pnl}, profit_factor={profit_factor}, max_drawdown={max_dd}")

    return {
        "n_closed_trades": n,
        "win_rate_pct": win_rate_pct,
        "total_pnl": total_pnl,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "avg_pnl_per_trade": round(float(profits.mean()), 6),
        "avg_win": round(float(wins.mean()), 6) if len(wins) else 0.0,
        "avg_loss": round(float(losses.mean()), 6) if len(losses) else 0.0,
        "largest_win": round(float(wins.max()), 6) if len(wins) else 0.0,
        "largest_loss": round(float(losses.min()), 6) if len(losses) else 0.0,
        "profit_factor": profit_factor,
        "max_drawdown": max_dd,
        "pd_ratio": pd_ratio,
        "sharpe_ratio_annualised": sharpe,
        "max_consecutive_losses": max_consec_loss,
    }


def compute_execution_metrics(closed_df: pd.DataFrame) -> dict:
    """Execution-cost and behaviour diagnostics: spread drag, how trades
    actually exited (signal vs. forced time-exit), limit vs. market fills."""
    out = {}
    if closed_df.empty:
        return out

    if "spread_cost" in closed_df.columns:
        total_spread = round(float(closed_df["spread_cost"].fillna(0).sum()), 6)
        out["total_spread_cost"] = total_spread
        if "profit" in closed_df.columns:
            gross_profit_sum = float(closed_df.loc[closed_df["profit"] > 0, "profit"].sum())
            if gross_profit_sum > 0:
                out["spread_cost_pct_of_gross_profit"] = round(
                    total_spread / gross_profit_sum * 100, 2
                )

    if "holding_duration" in closed_df.columns:
        hd = closed_df["holding_duration"].dropna()
        if len(hd):
            out["avg_holding_duration"] = round(float(hd.mean()), 2)
            out["max_holding_duration_observed"] = float(hd.max())
        if "max_holding_duration" in closed_df.columns:
            valid = closed_df.dropna(subset=["holding_duration", "max_holding_duration"])
            if len(valid):
                hit_cap = valid["holding_duration"] >= valid["max_holding_duration"]
                out["pct_trades_hit_max_holding"] = round(float(hit_cap.mean() * 100), 2)

    if "is_limit" in closed_df.columns and "profit" in closed_df.columns:
        breakdown = {}
        for is_limit_val, label in ((True, "limit"), (False, "market")):
            sub = closed_df[closed_df["is_limit"] == is_limit_val]
            p = sub["profit"].dropna()
            if len(p):
                breakdown[label] = {
                    "n_trades": int(len(sub)),
                    "win_rate_pct": round(float((p > 0).mean() * 100), 2),
                    "avg_profit": round(float(p.mean()), 6),
                }
        if breakdown:
            out["order_type_breakdown"] = breakdown

    if out:
        info(f"Execution metrics computed: {list(out.keys())}")
    return out


def compute_group_breakdown(closed_df: pd.DataFrame, column: str) -> dict:
    """Win rate / PnL grouped by an arbitrary column (asset, timeframe, MA type)."""
    if column not in closed_df.columns or closed_df.empty or "profit" not in closed_df.columns:
        return {}
    result = {}
    for key, sub in closed_df.groupby(column):
        p = sub["profit"].dropna()
        if not len(p):
            continue
        result[str(key)] = {
            "n_trades": int(len(sub)),
            "win_rate_pct": round(float((p > 0).mean() * 100), 2),
            "total_pnl": round(float(p.sum()), 6),
            "avg_pnl": round(float(p.mean()), 6),
        }
    if result:
        info(f"Breakdown by '{column}': {len(result)} group(s) — {list(result.keys())}")
    return result


def compute_entry_condition_breakdown(closed_df: pd.DataFrame) -> dict:
    """Was the strategy's entry signal actually well-conditioned? Buckets
    profit by RSI zone (relative to that trade's own thresholds) and by
    volatility tercile — the two things worth checking when tuning."""
    out = {}
    if closed_df.empty or "profit" not in closed_df.columns:
        return out

    required = {"rsi", "overbought_thresh", "oversold_thresh"}
    if required.issubset(closed_df.columns):
        sub = closed_df.dropna(subset=list(required) + ["profit"])
        if len(sub):
            def _rsi_bucket(row):
                if row["rsi"] >= row["overbought_thresh"]:
                    return "overbought"
                if row["rsi"] <= row["oversold_thresh"]:
                    return "oversold"
                return "neutral"

            sub = sub.assign(_bucket=sub.apply(_rsi_bucket, axis=1))
            rsi_breakdown = {}
            for key, g in sub.groupby("_bucket"):
                rsi_breakdown[key] = {
                    "n_trades": int(len(g)),
                    "win_rate_pct": round(float((g["profit"] > 0).mean() * 100), 2),
                    "avg_pnl": round(float(g["profit"].mean()), 6),
                }
            if rsi_breakdown:
                out["by_rsi_entry_zone"] = rsi_breakdown

    if "combined_volatility_score" in closed_df.columns:
        sub = closed_df.dropna(subset=["combined_volatility_score", "profit"])
        if len(sub) >= 6 and sub["combined_volatility_score"].nunique() >= 3:
            try:
                sub = sub.assign(
                    _bucket=pd.qcut(
                        sub["combined_volatility_score"], 3,
                        labels=["low", "medium", "high"], duplicates="drop",
                    )
                )
                vol_breakdown = {}
                for key, g in sub.groupby("_bucket", observed=True):
                    vol_breakdown[str(key)] = {
                        "n_trades": int(len(g)),
                        "win_rate_pct": round(float((g["profit"] > 0).mean() * 100), 2),
                        "avg_pnl": round(float(g["profit"].mean()), 6),
                    }
                if vol_breakdown:
                    out["by_volatility_tercile"] = vol_breakdown
            except ValueError:
                warning("Could not bucket combined_volatility_score into terciles "
                        "(not enough distinct values in this run).", __file__)

    if "moving_average_type" in closed_df.columns and closed_df["moving_average_type"].nunique() > 1:
        ma_breakdown = compute_group_breakdown(closed_df, "moving_average_type")
        if ma_breakdown:
            out["by_moving_average_type"] = ma_breakdown

    info(f"Entry-condition breakdowns computed: {list(out.keys())}")
    return out


# ---------------------------------------------------------------------------
# 3. Charts
# ---------------------------------------------------------------------------

def _fig_to_b64(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("utf-8")


def build_charts(closed_df: pd.DataFrame, figures_dir: Path | None = None) -> dict:
    """Builds each chart, saves a PNG into figures_dir (if given), and
    returns a dict of base64-encoded PNGs for embedding directly in the HTML."""
    charts = {}
    if closed_df.empty or "profit" not in closed_df.columns:
        warning("No closed trades with profit — skipping chart generation.", __file__)
        return charts

    df = closed_df.dropna(subset=["profit"]).copy()
    if df.empty:
        warning("All closed trades are missing a profit value — skipping chart generation.", __file__)
        return charts

    info("Building performance charts (equity curve, drawdown, PnL distribution, per-asset)...")
    profits = df["profit"].astype(float)
    cum_pnl = profits.cumsum().reset_index(drop=True)
    xcol = "exit_date" if "exit_date" in df.columns and df["exit_date"].notna().any() else None

    def _save(fig, name):
        if figures_dir is not None:
            Path(figures_dir).mkdir(parents=True, exist_ok=True)
            fig.savefig(Path(figures_dir) / f"{name}.png", dpi=120, bbox_inches="tight")
        return _fig_to_b64(fig)

    # --- Equity curve ---
    fig, ax = plt.subplots(figsize=(10, 4))
    if xcol:
        ax.plot(df[xcol].values, cum_pnl.values, linewidth=1.2, color="#1f77b4")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
        fig.autofmt_xdate()
    else:
        ax.plot(cum_pnl.values, linewidth=1.2, color="#1f77b4")
        ax.set_xlabel("Trade #")
    ax.axhline(0, color="red", linestyle="--", linewidth=0.8)
    ax.set_title("Cumulative PnL (Equity Curve)")
    ax.set_ylabel("PnL")
    ax.grid(True, alpha=0.3)
    charts["equity_curve"] = _save(fig, "equity_curve")
    plt.close(fig)

    # --- Drawdown ---
    roll_max = cum_pnl.cummax()
    drawdown = roll_max - cum_pnl
    fig, ax = plt.subplots(figsize=(10, 3))
    if xcol:
        ax.fill_between(df[xcol].values, -drawdown.values, 0, color="crimson", alpha=0.5)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
        fig.autofmt_xdate()
    else:
        ax.fill_between(range(len(drawdown)), -drawdown.values, 0, color="crimson", alpha=0.5)
        ax.set_xlabel("Trade #")
    ax.set_title("Drawdown")
    ax.set_ylabel("Drawdown")
    ax.grid(True, alpha=0.3)
    charts["drawdown"] = _save(fig, "drawdown")
    plt.close(fig)

    # --- PnL distribution ---
    fig, ax = plt.subplots(figsize=(8, 4))
    bins = min(40, max(5, len(profits) // 2)) or 5
    ax.hist(profits.values, bins=bins, color="#2ca02c", edgecolor="white", linewidth=0.4)
    ax.axvline(0, color="red", linestyle="--", linewidth=0.8)
    ax.set_title("Trade PnL Distribution")
    ax.set_xlabel("PnL per Trade")
    ax.set_ylabel("Frequency")
    ax.grid(True, alpha=0.3)
    charts["pnl_dist"] = _save(fig, "pnl_distribution")
    plt.close(fig)

    # --- Cumulative PnL by asset (overlaid) ---
    if "asset" in df.columns and xcol:
        fig, ax = plt.subplots(figsize=(11, 5))
        for asset in sorted(df["asset"].dropna().unique()):
            sub = df[df["asset"] == asset].sort_values(xcol)
            cum = sub["profit"].cumsum()
            ax.plot(sub[xcol].values, cum.values, linewidth=1.2, marker="o", markersize=2.5, label=asset)
        ax.axhline(0, color="black", linewidth=0.6, linestyle="--")
        ax.set_title("Cumulative PnL by Asset")
        ax.set_ylabel("Cum PnL")
        ax.set_xlabel("Exit date")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
        ax.grid(True, alpha=0.3)
        ax.legend(loc="center left", bbox_to_anchor=(1.02, 0.5), fontsize=8)
        fig.autofmt_xdate()
        fig.tight_layout()
        charts["equity_by_asset"] = _save(fig, "equity_by_asset")
        plt.close(fig)

    info(f"Built {len(charts)} chart(s)" + (f", saved as PNGs to {figures_dir}" if figures_dir else ""))
    return charts


# ---------------------------------------------------------------------------
# 4. HTML report
# ---------------------------------------------------------------------------

def _fmt(v):
    if isinstance(v, float) and math.isnan(v):
        return "N/A"
    if isinstance(v, float) and math.isinf(v):
        return "∞"
    return v


def _kv_table(d: dict, title: str) -> str:
    if not d:
        return ""
    rows = "".join(f"<tr><td>{k}</td><td><strong>{_fmt(v)}</strong></td></tr>" for k, v in d.items())
    return f"<h3>{title}</h3><table><tbody>{rows}</tbody></table>"


def _nested_table(d: dict, title: str) -> str:
    """Renders {row_label: {col: value, ...}, ...} as a table."""
    if not d:
        return ""
    cols = []
    for v in d.values():
        for k in v.keys():
            if k not in cols:
                cols.append(k)
    header = "".join(f"<th>{c}</th>" for c in cols)
    rows = ""
    for key, v in d.items():
        cells = "".join(f"<td>{_fmt(v.get(c, ''))}</td>" for c in cols)
        rows += f"<tr><td><strong>{key}</strong></td>{cells}</tr>"
    return f"<h3>{title}</h3><table><thead><tr><th></th>{header}</tr></thead><tbody>{rows}</tbody></table>"


def write_html(metrics: dict, charts: dict, out_path: Path, trades_csv: Path):
    perf = metrics.get("performance", {})
    coverage = metrics.get("coverage", {})
    status = metrics.get("status_counts", {})
    execution = metrics.get("execution", {})

    win_good = perf.get("win_rate_pct", 0) >= 50
    pf_good = perf.get("profit_factor", 0) not in (None,) and perf.get("profit_factor", 0) >= 1.5
    sharpe_val = perf.get("sharpe_ratio_annualised", float("nan"))
    sharpe_good = isinstance(sharpe_val, (int, float)) and not math.isnan(sharpe_val) and sharpe_val >= 1.0
    pnl_good = perf.get("total_pnl", 0) > 0

    def row(label, value, good=None):
        colour = "#d4edda" if good is True else "#f8d7da" if good is False else "#ffffff"
        return f'<tr style="background:{colour}"><td>{label}</td><td><strong>{_fmt(value)}</strong></td></tr>'

    summary_rows = "".join([
        row("Total Trades (all statuses)", status.get("total_trades", "—")),
        row("Closed", status.get("closed", "—")),
        row("Still Open", status.get("open", "—")),
        row("Cancelled", status.get("cancelled", "—")),
        row("Win Rate", f'{perf.get("win_rate_pct", "—")}%', good=win_good),
        row("Total PnL", perf.get("total_pnl", "—"), good=pnl_good),
        row("Avg PnL / Trade", perf.get("avg_pnl_per_trade", "—")),
        row("Avg Win", perf.get("avg_win", "—")),
        row("Avg Loss", perf.get("avg_loss", "—")),
        row("Largest Win", perf.get("largest_win", "—")),
        row("Largest Loss", perf.get("largest_loss", "—")),
        row("Profit Factor", perf.get("profit_factor", "—"), good=pf_good),
        row("Max Drawdown", perf.get("max_drawdown", "—")),
        row("PD Ratio", perf.get("pd_ratio", "—")),
        row("Sharpe Ratio (ann.)", perf.get("sharpe_ratio_annualised", "—"), good=sharpe_good),
        row("Max Consecutive Losses", perf.get("max_consecutive_losses", "—")),
    ])

    coverage_html = _kv_table({
        "Date range": f'{coverage.get("data_start", "—")} → {coverage.get("data_end", "—")}',
        "Assets": ", ".join(coverage.get("assets", [])) or "—",
        "Timeframe(s)": ", ".join(coverage.get("timeframes", [])) or "—",
    }, "Data Coverage")

    execution_html = _kv_table({
        "Total spread cost": execution.get("total_spread_cost", "—"),
        "Spread cost as % of gross profit": execution.get("spread_cost_pct_of_gross_profit", "—"),
        "Avg holding duration": execution.get("avg_holding_duration", "—"),
        "% trades that hit max holding cap": execution.get("pct_trades_hit_max_holding", "—"),
    }, "Execution & Holding Behaviour")

    order_type_html = _nested_table(execution.get("order_type_breakdown", {}), "Limit vs. Market Fills")
    close_reason_html = _kv_table(status.get("close_reason_breakdown", {}), "How Trades Exited")
    asset_html = _nested_table(metrics.get("by_asset", {}), "By Asset")
    timeframe_html = _nested_table(metrics.get("by_timeframe", {}), "By Timeframe")

    entry = metrics.get("entry_conditions", {})
    rsi_html = _nested_table(entry.get("by_rsi_entry_zone", {}), "By RSI Entry Zone")
    vol_html = _nested_table(entry.get("by_volatility_tercile", {}), "By Volatility Tercile")
    ma_html = _nested_table(entry.get("by_moving_average_type", {}), "By Moving Average Type")

    chart_html = ""
    for title, key in [
        ("Equity Curve", "equity_curve"),
        ("Drawdown", "drawdown"),
        ("PnL Distribution", "pnl_dist"),
        ("Cumulative PnL by Asset", "equity_by_asset"),
    ]:
        if key in charts:
            chart_html += f'<h3>{title}</h3><img src="data:image/png;base64,{charts[key]}" style="max-width:100%;margin-bottom:24px;">'

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
  </style>
</head>
<body>
  <h1>Backtest Performance Report</h1>
  <p class="meta">
    Generated: {metrics.get("generated_at", "—")}<br>
    Trade records: <code>{trades_csv}</code>
  </p>

  {coverage_html}

  <h2>Summary</h2>
  <table><thead><tr><th>Metric</th><th>Value</th></tr></thead><tbody>{summary_rows}</tbody></table>

  {execution_html}
  {order_type_html}
  {close_reason_html}

  <h2>Breakdowns</h2>
  {asset_html}
  {timeframe_html}
  {rsi_html}
  {vol_html}
  {ma_html}

  <h2>Charts</h2>
  {chart_html}
</body>
</html>"""

    out_path = Path(out_path)
    out_path.write_text(html, encoding="utf-8")
    info(f"HTML report written to: {out_path}")


# ---------------------------------------------------------------------------
# 5. Orchestration — the single entry point run_backtest.py calls
# ---------------------------------------------------------------------------

def generate_report(run_dir, trades_csv=None) -> dict:
    """Reads <run_dir>/trades.csv, computes every metric above, and writes
    metrics.json + report.html + figures/*.png into that same run_dir."""
    run_dir = Path(run_dir)
    trades_csv = Path(trades_csv) if trades_csv else run_dir / "trades.csv"
    info(f"Generating metrics report for run: {run_dir}")

    if not trades_csv.exists():
        error(f"No trades.csv found at {trades_csv}", __file__)
        raise FileNotFoundError(f"No trades.csv found at {trades_csv}")

    figures_dir = run_dir / "figures"

    df = load_trades_raw(trades_csv)
    closed = closed_trades(df)

    metrics = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "trades_csv": str(trades_csv),
        "coverage": compute_coverage(df),
        "status_counts": compute_status_counts(df),
        "performance": compute_performance_metrics(closed),
        "execution": compute_execution_metrics(closed),
        "by_asset": compute_group_breakdown(closed, "asset"),
        "by_timeframe": (
            compute_group_breakdown(closed, "time_frame")
            if "time_frame" in df.columns and df["time_frame"].nunique() > 1
            else {}
        ),
        "entry_conditions": compute_entry_condition_breakdown(closed),
    }

    charts = build_charts(closed, figures_dir=figures_dir)

    metrics_path = run_dir / "metrics.json"
    metrics_path.write_text(json.dumps(metrics, indent=2, default=str), encoding="utf-8")
    info(f"Metrics JSON written to: {metrics_path}")

    report_path = run_dir / "report.html"
    write_html(metrics, charts, report_path, trades_csv)

    perf = metrics.get("performance", {})
    if "error" in perf:
        warning(f"Report generated with no performance metrics: {perf['error']}", __file__)
    else:
        info("========== PERFORMANCE SUMMARY ==========")
        for k, v in perf.items():
            info(f"  {k:<28} {v}")
        info("==========================================")

    info(f"Report generation complete for run: {run_dir}")
    return metrics
