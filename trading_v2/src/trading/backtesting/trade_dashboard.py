# Builds dashboard.html for one backtest run: headline stats, a stats row per pair, net pips per year, and
# interactive charts: all pairs' equity together, then one price/trades/equity/drawdown chart per pair. Called at the end of scripts/run_backtest.py.
# Uses only the run's own trades and the price data the run loaded, so nothing outside the config's dates.
# All numbers are in net pips per unit (after costs), so they don't depend on position size.
from trading.backtesting.risk_metrics import account_metrics, daily_returns_from_equity
import json
import os

import numpy as np
import pandas as pd

from trading.utils.logger import info


def pip_size(pair):
    return 0.01 if "JPY" in pair else 0.0001


def compute_stats(trades):
    p = trades["profit"]
    equity = p.cumsum()
    drawdown = equity - equity.cummax()

    # Daily P&L on every weekday of the run (days with no trade count as 0), for the Sharpe ratio
    days = pd.bdate_range(trades["entry_date"].min().normalize(), trades["exit_date"].max().normalize())
    daily = p.groupby(trades["exit_date"].dt.normalize()).sum().reindex(days, fill_value=0.0)

    # Longest time spent below a previous equity high
    peak_time = trades["exit_date"].where(drawdown == 0).ffill()
    longest_dd_days = (trades["exit_date"] - peak_time).dt.days.max()

    wins, losses = p[p > 0], p[p <= 0]
    by_year = trades.groupby(trades["entry_date"].dt.year)["profit"]
    return {
        "Trades": len(p),
        "Net pips (total)": p.sum(),
        "Net pips per trade": p.mean(),
        "Gross pips per trade": trades["gross_pips"].mean(),
        "t-stat": p.mean() / p.std() * np.sqrt(len(p)) if len(p) > 1 else np.nan,
        "Sharpe (annual, daily P&L)": daily.mean() / daily.std() * np.sqrt(252) if daily.std() > 0 else np.nan,
        "Max drawdown (pips)": drawdown.min(),
        "Longest drawdown (days)": longest_dd_days,
        "Win rate %": 100 * len(wins) / len(p),
        "Average win (pips)": wins.mean(),
        "Average loss (pips)": losses.mean(),
        "Profit factor": wins.sum() / -losses.sum() if losses.sum() < 0 else np.nan,
        "Years positive": f"{(by_year.sum() > 0).sum()} of {by_year.ngroups}",
        "Stopped out %": 100 * (trades["reason"] == "stop").mean(),
    }


def price_traces(pair, price, trades):
    # Price line for one pair with its buy/sell entries (triangles), exits (crosses) and a dotted line per trade
    fmt_t = lambda s: s.dt.strftime("%Y-%m-%d %H:%M").tolist()
    idx = price.index.tz_localize("UTC").tz_convert("Europe/London").tz_localize(None)   # London time, like trades.csv
    traces = [{"x": idx.strftime("%Y-%m-%d %H:%M").tolist(), "y": price["Close"].round(5).tolist(),
               "name": f"{pair} price", "type": "scattergl", "mode": "lines", "line": {"color": "grey", "width": 1}}]
    for side, colour, symbol, name in [(1, "green", "triangle-up", "buy"), (-1, "red", "triangle-down", "sell")]:
        s = trades[trades["side"] == side]
        lx, ly = [], []
        for r in s.itertuples():   # dotted line from each entry to its exit (None breaks it between trades)
            lx += [r.entry_date.strftime("%Y-%m-%d %H:%M"), r.exit_date.strftime("%Y-%m-%d %H:%M"), None]
            ly += [r.entry, r.exit, None]
        traces.append({"x": lx, "y": ly, "name": f"{name} trades", "type": "scattergl", "mode": "lines",
                       "line": {"color": colour, "width": 1, "dash": "dot"}, "hoverinfo": "skip"})
        traces.append({"x": fmt_t(s["entry_date"]), "y": s["entry"].tolist(), "name": f"{name} entries",
                       "type": "scattergl", "mode": "markers", "marker": {"color": colour, "symbol": symbol, "size": 9},
                       "text": [f"{r.reason}, {r.profit:.1f} pips net" for r in s.itertuples()]})
    traces.append({"x": fmt_t(trades["exit_date"]), "y": trades["exit"].tolist(), "name": "exits", "type": "scattergl",
                   "mode": "markers", "marker": {"color": "black", "symbol": "x", "size": 7}})
    return traces


def equity_traces(trades, name, colour, with_drawdown):
    # Running total of net pips (and optionally the drawdown below it)
    fmt_t = lambda s: s.dt.strftime("%Y-%m-%d %H:%M").tolist()
    equity = trades["profit"].cumsum()
    traces = [{"x": fmt_t(trades["exit_date"]), "y": equity.round(1).tolist(), "name": name,
               "type": "scattergl", "mode": "lines", "line": {"color": colour}, "yaxis": "y2"}]
    if with_drawdown:
        traces.append({"x": fmt_t(trades["exit_date"]), "y": (equity - equity.cummax()).round(1).tolist(),
                       "name": f"{name} drawdown", "type": "scatter", "mode": "lines", "fill": "tozeroy",
                       "line": {"color": "firebrick", "width": 1}, "yaxis": "y3"})
    return traces


def build_dashboard(run_dir, data_list, params, open_browser=True):
    trades = pd.read_csv(os.path.join(run_dir, "trades.csv"), parse_dates=["entry_date", "exit_date"])
    if trades.empty:
        return None
    trades = trades.sort_values("exit_date").reset_index(drop=True)
    stats = compute_stats(trades)
    pairs = params["pairs"]
    colours = ["royalblue", "darkorange", "seagreen", "purple", "brown", "deeppink", "olive", "teal"]
    charts = []   # (div id, heading, traces, layout), drawn in this order on the page

    # --- All pairs together: total equity and drawdown, plus each pair's equity ---
    if len(pairs) > 1:
        traces = equity_traces(trades, "all pairs", "black", with_drawdown=True)
        for k, pair in enumerate(pairs):
            traces += equity_traces(trades[trades["asset"] == pair].reset_index(drop=True), pair, colours[k % 8], False)
        charts.append(("all", "All pairs: equity and drawdown (net pips)", traces,
                       {"height": 500, "hovermode": "closest", "margin": {"t": 30},
                        "yaxis2": {"title": "equity (pips)", "domain": [0.3, 1]},
                        "yaxis3": {"title": "drawdown", "domain": [0, 0.25]}}))

    # --- One chart per pair: price with trades, equity and drawdown (shared time axis) ---
    for k, (pair, price) in enumerate(zip(pairs, data_list)):
        t = trades[trades["asset"] == pair].reset_index(drop=True)
        if t.empty:
            continue
        traces = price_traces(pair, price, t) + equity_traces(t, f"{pair} equity", colours[k % 8], with_drawdown=True)
        charts.append((f"pair{k}", f"{pair}: price, trades, equity and drawdown", traces,
                       {"height": 900, "hovermode": "closest", "margin": {"t": 30},
                        "yaxis": {"title": "price", "domain": [0.45, 1]},
                        "yaxis2": {"title": "equity (pips)", "domain": [0.2, 0.42]},
                        "yaxis3": {"title": "drawdown", "domain": [0, 0.17]}}))

    # --- Net pips per year, one bar per pair ---
    by_pair_year = trades.groupby([trades["entry_date"].dt.year, "asset"])["profit"].sum().unstack("asset")
    year_traces = [{"x": by_pair_year.index.astype(str).tolist(), "y": by_pair_year[pair].fillna(0).round(1).tolist(),
                    "name": pair, "type": "bar", "marker": {"color": colours[k % 8]}}
                   for k, pair in enumerate(pairs) if pair in by_pair_year]
    charts.append(("years", "Net pips per year", year_traces,
                   {"height": 350, "margin": {"t": 30}, "barmode": "group", "yaxis": {"title": "net pips"}}))

    def fmt(v):
        return f"{v:,.2f}" if isinstance(v, (float, np.floating)) else str(v)

    stat_cells = "".join(f"<div class='stat'><div class='label'>{k}</div><div class='value'>{fmt(v)}</div></div>"
                         for k, v in stats.items())

    # Account metrics (% returns of the account, from equity.csv: starting capital + every pair's P&L incl. costs)
    account_cells = ""
    equity_path = os.path.join(run_dir, "equity.csv")
    if os.path.exists(equity_path):
        pnl = pd.read_csv(equity_path, index_col=0, parse_dates=True).sum(axis=1)
        account = params["starting_capital"] + pnl
        metrics = account_metrics(daily_returns_from_equity(account), 252, win_rate=stats["Win rate %"])
        account_cells = "".join(f"<div class='stat'><div class='label'>{k}</div><div class='value'>{fmt(v)}</div></div>"
                                for k, v in metrics.items())
        stats.update({f"Account {k}": v for k, v in metrics.items()})

        # Optional benchmark, e.g. params["benchmark"] = {"name": "S&P 500 buy and hold", "price": <daily close Series>}
        benchmark = params.get("benchmark")
        if benchmark is not None:
            bench = benchmark["price"].reindex(account.index, method="ffill").bfill()
            bench = params["starting_capital"] * bench / bench.iloc[0]
            traces = []
            for series, label, colour in [(account, "strategy", "royalblue"), (bench, benchmark["name"], "grey")]:
                x = series.index.strftime("%Y-%m-%d").tolist()
                traces.append({"x": x, "y": (100 * (series / series.iloc[0] - 1)).round(2).tolist(), "name": f"{label} equity",
                               "type": "scattergl", "mode": "lines", "line": {"color": colour}, "yaxis": "y2"})
                traces.append({"x": x, "y": (100 * (series / series.cummax() - 1)).round(2).tolist(), "name": f"{label} drawdown",
                               "type": "scattergl", "mode": "lines", "line": {"color": colour}, "fill": "tozeroy", "yaxis": "y3"})
            charts.insert(0, ("bench", f"Account vs {benchmark['name']}: return and drawdown (%)", traces,
                              {"height": 550, "hovermode": "x unified", "margin": {"t": 30},
                               "yaxis2": {"title": "return %", "domain": [0.35, 1]},
                               "yaxis3": {"title": "drawdown %", "domain": [0, 0.3]}}))
            bench_metrics = account_metrics(daily_returns_from_equity(bench), 252)
            account_cells += "".join(f"<div class='stat' style='background:#f3f3f3'><div class='label'>{benchmark['name']}: {k}</div>"
                                     f"<div class='value'>{fmt(v)}</div></div>" for k, v in bench_metrics.items()
                                     if k in ("CAGR %", "Sharpe", "Max drawdown %", "Calmar", "Ulcer index"))

    # Stats table with one row per pair
    pair_stats = {pair: compute_stats(trades[trades["asset"] == pair].reset_index(drop=True))
                  for pair in pairs if (trades["asset"] == pair).sum() > 1}
    cols = ["Trades", "Net pips per trade", "t-stat", "Sharpe (annual, daily P&L)", "Max drawdown (pips)",
            "Profit factor", "Win rate %", "Years positive"]
    pair_rows = "".join(f"<tr><td>{pair}</td>" + "".join(f"<td>{fmt(s[c])}</td>" for c in cols) + "</tr>"
                        for pair, s in pair_stats.items())
    pair_table = f"<table><tr><th>Pair</th>{''.join(f'<th>{c}</th>' for c in cols)}</tr>{pair_rows}</table>"

    by_year = trades.groupby(trades["entry_date"].dt.year)["profit"].agg(["count", "mean", "sum"])
    year_rows = "".join(f"<tr><td>{y}</td><td>{r['count']:.0f}</td><td>{r['mean']:.2f}</td><td>{r['sum']:.1f}</td></tr>"
                        for y, r in by_year.iterrows())
    title = f"{params['strategy_name']} &middot; {', '.join(pairs)} &middot; {os.path.basename(run_dir)}"
    chart_divs = "".join(f"<h2>{heading}</h2><div id='{div}'></div>" for div, heading, _, _ in charts)
    chart_js = "".join(f"Plotly.newPlot('{div}', {json.dumps(tr)}, {json.dumps(lay)}, {{responsive: true}});\n"
                       for div, _, tr, lay in charts)

    html = f"""<!doctype html><html><head><meta charset="utf-8"><title>{params['strategy_name']} dashboard</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
 body {{ font-family: -apple-system, Helvetica, Arial, sans-serif; margin: 20px; color: #222; background: #fff; }}
 h1 {{ font-size: 20px; margin: 0 0 4px; }} .sub {{ color: #666; margin-bottom: 16px; }}
 .stats {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 10px; margin-bottom: 20px; }}
 .stat {{ border: 1px solid #ddd; border-radius: 8px; padding: 10px; }}
 .label {{ font-size: 12px; color: #666; }} .value {{ font-size: 20px; font-weight: 600; }}
 table {{ border-collapse: collapse; margin: 10px 0 20px; }} td, th {{ border: 1px solid #ddd; padding: 4px 10px; text-align: right; }}
 h2 {{ font-size: 16px; margin-top: 24px; }}
</style></head><body>
<h1>{title}</h1>
<div class="sub">All figures are net pips per unit traded, after costs. Drag on a chart to zoom, double-click to zoom out.</div>
<div class="stats">{stat_cells}</div>
<h2>Account (% returns, daily, after all costs)</h2>
<div class="stats">{account_cells}</div>
<h2>By pair</h2>{pair_table}
{chart_divs}
<table><tr><th>Year</th><th>Trades</th><th>Net pips per trade</th><th>Net pips total</th></tr>{year_rows}</table>
<script>
{chart_js}</script></body></html>"""

    path = os.path.join(run_dir, "dashboard.html")
    unit = params.get("profit_unit", "pips")
    if unit != "pips":
        # strategies that measure profit in % of the account (e.g. month_end_stocks_bonds.py) relabel the page
        html = html.replace("net pips per unit traded", f"net {unit} of the account per trade").replace("pips", unit)
    with open(path, "w") as f:
        f.write(html)
    info(f"Dashboard saved to {path}")
    if open_browser:
        import webbrowser
        webbrowser.open("file://" + os.path.abspath(path))
    return stats
