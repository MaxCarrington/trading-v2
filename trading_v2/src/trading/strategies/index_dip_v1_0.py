# Index dip buy v1.0 (daily bars) - the SPY rule from the r/algotrading post (u/tanweer919), copied exactly, no tuning.
#
# Rules:
# 1. Only when the close is above its 200-day average (dips in an uptrend).
# 2. Buy at the next open if ANY of: RSI(2) under 10, 3 down closes in a row, or the close in the bottom 20%
#    of the day's range (IBS = (close - low) / (high - low) < 0.2).
# 3. Sell at the next open after the first close above the 5-day average, or after 10 days.
# 4. Stop: a close 8% below the entry -> sell at the next open. After a stop, wait for a close above the
#    5-day average before buying again.
# 5. Size: all of the account (position_fraction of it), no leverage.
#
# Data rules: research 2005-2018 only. These rules were fixed before any test.
import pandas as pd

def rsi(closes, n=2):
    # Wilder's RSI on the last 100 closes
    change = pd.Series(closes[-100:]).diff().dropna()
    gain = change.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean().iloc[-1]
    loss = (-change.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean().iloc[-1]
    if loss == 0:
        return 100.0
    return 100 - 100 / (1 + gain / loss)

def index_dip_v1_0(store, new_row_list, current_pos, account_info, params):
    series = params["pairs"]
    if store is None:
        store = {"closes": {s: [] for s in series}, "open_trade": {s: None for s in series},
                 "wait_after_stop": {s: False for s in series}, "trade_list": {s: [] for s in series}}
    market = [0] * len(series)

    for i, (symbol, row) in enumerate(zip(series, new_row_list)):
        closes = store["closes"][symbol]
        closes.append(row["Close"])
        trade_date = pd.Timestamp((row["Time"] + pd.Timedelta(hours=2)).date())   # daily bars start 22:00 UTC
        if len(closes) < 201:
            continue
        above_sma5 = closes[-1] > sum(closes[-5:]) / 5
        if above_sma5:
            store["wait_after_stop"][symbol] = False

        if current_pos[i] == 0:
            if store["open_trade"][symbol] is not None:          # the exit filled at this bar's open
                close_trade(store, symbol, row, trade_date, params)
            uptrend = closes[-1] > sum(closes[-200:]) / 200
            day_range = row["High"] - row["Low"]
            ibs = (row["Close"] - row["Low"]) / day_range if day_range > 0 else 0.5
            three_down = closes[-1] < closes[-2] < closes[-3] < closes[-4]
            dip = rsi(closes) < 10 or three_down or ibs < 0.2
            if uptrend and dip and not store["wait_after_stop"][symbol]:
                market[i] = round(account_info["balance"] * params["position_fraction"] / row["Close"], 3)   # fractional units: one JP225 unit costs more than the account
        else:
            trade = store["open_trade"][symbol]
            if trade is None:                                      # the entry filled at this bar's open
                trade = store["open_trade"][symbol] = {"entry": row["Open"], "entry_date": trade_date, "days": 0}
            trade["days"] += 1
            stopped = closes[-1] <= trade["entry"] * (1 - params["stop_pct"] / 100)
            if above_sma5 or trade["days"] >= params["max_hold_days"] or stopped:
                market[i] = -current_pos[i]
                trade["reason"] = "stop" if stopped else "sma5" if above_sma5 else "time"
                if stopped:
                    store["wait_after_stop"][symbol] = True

    return {"marketOrders": market, "store": store}

def close_trade(store, symbol, row, trade_date, params):
    # profit in % of the entry price, after the commission on entry and exit
    trade = store["open_trade"][symbol]
    gross = 100 * (row["Open"] / trade["entry"] - 1)
    cost = 2 * params["costs"]["commission_pct"] + 100 * params["costs"]["spread_pips"].get(symbol, 0) / row["Open"]
    store["trade_list"][symbol].append({
        "asset": symbol, "time_frame": params["timeframe"], "entry_date": trade["entry_date"], "exit_date": trade_date,
        "side": 1, "entry": trade["entry"], "exit": row["Open"], "days": trade["days"],
        "gross_pips": gross, "profit": gross - cost, "reason": trade["reason"],   # "pips" here = % per trade
    })
    store["open_trade"][symbol] = None
