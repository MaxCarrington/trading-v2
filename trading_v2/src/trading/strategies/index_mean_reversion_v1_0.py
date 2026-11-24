# Index mean reversion v1.0 (daily bars, index CFDs: SPX500, DE30, UK100, JP225)
#
# Idea (Larry Connors' RSI(2) system, Ernie Chan's short-term index mean reversion):
# stock indices drift up over time, and after a sharp short-term drop they tend to bounce within a few days.
# Buy the dip, sell the bounce. Long only, because the upward drift is on the long side.
#
# Rules (all fixed before any results were looked at):
# 1. Signal at the daily close: RSI(2) below entry_rsi (a sharp 1-3 day drop).
#    trend_filter true: only if the close is also above its 200-day average (dips in an uptrend).
# 2. Enter long at the next bar's open. Size: notional = leverage x the account (1 = no leverage).
# 3. Exit at the next open when: exit_rule "sma5" -> the close is back above its 5-day average,
#    exit_rule "rsi70" -> RSI(2) is above 70; or after max_hold_days days whatever happens. No stop loss
#    (mean reversion stops cut the trades just before they bounce); the risk is controlled by the size.
# 4. Each index is traded in its own account and currency (DE30 in EUR, UK100 in GBP, SPX500/JP225 in USD),
#    and the walk-forward averages their monthly returns into one equal-weighted portfolio.
#
# Costs (config): spread + slippage in index points, overnight financing = the currency's interest rate + markup
# on long positions (dividends ignored, so slightly pessimistic).
# Data rules: research 2005-2018 only, chosen by walk-forward (scripts/walk_forward_portfolio.py).
import pandas as pd

def rsi(closes, n=2):
    # Wilder's RSI on the last 100 closes (enough for the smoothing to settle)
    change = pd.Series(closes[-100:]).diff().dropna()
    gain = change.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean().iloc[-1]
    loss = (-change.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean().iloc[-1]
    if loss == 0:
        return 100.0
    return 100 - 100 / (1 + gain / loss)

def index_mean_reversion_v1_0(store, new_row_list, current_pos, account_info, params):
    series = params["pairs"]
    if store is None:
        store = initialise_store(series)
    market = [0] * len(series)

    for i, (symbol, row) in enumerate(zip(series, new_row_list)):
        closes = store["closes"][symbol]
        closes.append(row["Close"])
        trade_date = pd.Timestamp((row["Time"] + pd.Timedelta(hours=2)).date())   # daily bars start 22:00 UTC
        if len(closes) < 201:
            continue
        r = rsi(closes)

        if current_pos[i] == 0:
            # A trade closed on the last bar: record it
            if store["open_trade"][symbol] is not None:
                close_trade(store, symbol, row, trade_date, params)
            # Rule 1: sharp drop (and in an uptrend, if the filter is on)
            uptrend = closes[-1] > sum(closes[-200:]) / 200
            if r < params["entry_rsi"] and (uptrend or not params["trend_filter"]):
                market[i] = int(account_info["balance"] * params["leverage"] / row["Close"])
        else:
            if store["open_trade"][symbol] is None:                       # entry filled at this bar's open
                store["open_trade"][symbol] = {"entry": row["Open"], "entry_date": trade_date, "bars": 0}
            store["open_trade"][symbol]["bars"] += 1
            # Rule 3: exit on the bounce, or after max_hold_days
            if params["exit_rule"] == "sma5":
                bounced = closes[-1] > sum(closes[-5:]) / 5
            else:
                bounced = r > 70
            if bounced or store["open_trade"][symbol]["bars"] >= params["max_hold_days"]:
                market[i] = -current_pos[i]
                store["open_trade"][symbol]["reason"] = "bounce" if bounced else "time"

    return {"marketOrders": market, "store": store}

def close_trade(store, symbol, row, trade_date, params):
    # exit filled at this bar's open; profit in index points after the spread and slippage of entry + exit
    trade = store["open_trade"][symbol]
    costs = params["costs"]
    spread = costs["spread_pips"].get(symbol, costs["spread_pips"].get("default", 0.0))
    gross = row["Open"] - trade["entry"]
    store["trade_list"][symbol].append({
        "asset": symbol, "time_frame": params["timeframe"],
        "entry_date": trade["entry_date"], "exit_date": trade_date, "side": 1,
        "entry": trade["entry"], "exit": row["Open"], "gross_pips": gross,
        "profit": gross - spread - 2 * costs["slippage_pips"], "reason": trade.get("reason", ""),
    })
    store["open_trade"][symbol] = None

def initialise_store(series):
    return {
        "closes":     {s: [] for s in series},
        "open_trade": {s: None for s in series},
        "trade_list": {s: [] for s in series},
    }
