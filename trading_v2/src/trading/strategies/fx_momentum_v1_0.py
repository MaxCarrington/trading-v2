# FX currency momentum v1.0 (daily bars, 7 USD pairs = 8 currencies)
#
# Idea (Menkhoff et al. 2012 "Currency momentum strategies", Ernie Chan's cross-sectional momentum):
# currencies that went up most over the last few months tend to keep outperforming the ones that went down most
# over the next month. Rank the currencies, buy the strongest, sell the weakest, hold for a month.
#
# Rules (all fixed before any results were looked at):
# 1. Universe: USD, EUR, GBP, JPY, CHF, AUD, NZD, CAD, traded through the 7 USD pairs. Cross pairs (EUR_JPY...)
#    are not needed: long EUR + short JPY is the same as long EUR_USD + long USD_JPY.
# 2. Score: each currency's return against USD from lookback_months ago to skip_months ago
#    (skip_months 1 = ignore the most recent month, which tends to reverse). USD's score is 0.
# 3. Once a month (first daily bar of the month): long the top_k currencies, short the bottom_k.
#    If USD is in the top or bottom, that leg is simply "hold USD" (no trade for it).
# 4. Size: each leg targets target_leg_vol (5%) annual volatility of the account, using the last vol_days (60)
#    days of daily returns. Calm currencies get bigger positions, wild ones smaller. Capped at max_leg_leverage x equity.
# 5. Rebalance every month to the new targets. Costs: spread + slippage on every change (config "costs"),
#    plus overnight swap from the rate gap minus a markup (config "financing").
#
# Data rules: research 2005-2018 only, chosen by walk-forward (scripts/walk_forward_portfolio.py).
import math
import pandas as pd
from trading.utils.logger import info

DAYS_PER_MONTH = 21

def currency_of(pair):
    # the non-USD currency in a USD pair, and whether it is the base (EUR_USD) or the quote (USD_JPY)
    base, quote = pair.split("_")
    return (base, True) if quote == "USD" else (quote, False)

def fx_momentum_v1_0(store, new_row_list, current_pos, account_info, params):
    series = params["pairs"]
    if store is None:
        store = initialise_store(series)

    num_series = len(series)
    market = [0] * num_series

    # trading date: OANDA daily bars start at 22:00 UTC the evening before
    trade_date = (new_row_list[0]["Time"] + pd.Timedelta(hours=2)).date()
    for symbol, row in zip(series, new_row_list):
        store["closes"][symbol].append(row["Close"])

    new_month = store["month"] is not None and trade_date.month != store["month"]
    store["month"] = trade_date.month
    lookback = params["lookback_months"] * DAYS_PER_MONTH
    skip = params["skip_months"] * DAYS_PER_MONTH
    enough_data = len(store["closes"][series[0]]) > max(lookback, params["vol_days"]) + 1

    if new_month and enough_data:
        # Rule 2: score every currency against USD
        scores = {"USD": 0.0}
        vols = {}
        for symbol in series:
            closes = store["closes"][symbol]
            ccy, is_base = currency_of(symbol)
            ret = closes[-1 - skip] / closes[-1 - lookback] - 1
            scores[ccy] = ret if is_base else 1 / (1 + ret) - 1      # USD_JPY up = JPY down
            daily = pd.Series(closes[-params["vol_days"] - 1:]).pct_change().dropna()
            vols[symbol] = daily.std() * math.sqrt(252)

        # Rule 3: long the top_k, short the bottom_k
        ranked = sorted(scores, key=scores.get, reverse=True)
        longs, shorts = ranked[:params["top_k"]], ranked[-params["top_k"]:]

        # Rule 4: volatility-scaled size for each leg, then trade the difference from the current position
        equity = account_info["balance"]
        for i, (symbol, row) in enumerate(zip(series, new_row_list)):
            ccy, is_base = currency_of(symbol)
            direction = 1 if ccy in longs else -1 if ccy in shorts else 0
            if not is_base:
                direction = -direction                                 # long JPY = sell USD_JPY
            notional = min(equity * params["target_leg_vol"] / vols[symbol], equity * params["max_leg_leverage"])
            units = notional / row["Close"] if is_base else notional   # EUR_USD: units of EUR; USD_JPY: units of USD
            target = int(direction * units)
            market[i] = target - current_pos[i]
            record_trades(store, symbol, current_pos[i], target, row, trade_date, params)
        store["last_ranking"] = ranked

    return {"marketOrders": market, "store": store}

def record_trades(store, symbol, old, new, row, trade_date, params):
    # For the trade list / dashboard only: one trade per leg from the month it opens to the month it closes or flips.
    # profit = spot pips minus the spread and slippage of opening and closing (resizing and swap are in the equity curve).
    pip = 0.01 if "JPY" in symbol else 0.0001
    old_side = (old > 0) - (old < 0)
    new_side = (new > 0) - (new < 0)
    if old_side == new_side:
        return
    open_trade = store["open_trade"][symbol]
    if open_trade is not None:
        gross = open_trade["side"] * (row["Close"] - open_trade["entry"]) / pip
        costs = params["costs"]
        spread = costs["spread_pips"].get(symbol, costs["spread_pips"].get("default", 0.0))
        store["trade_list"][symbol].append({
            "asset": symbol, "time_frame": params["timeframe"],
            "entry_date": open_trade["entry_date"], "exit_date": pd.Timestamp(trade_date),
            "side": open_trade["side"], "entry": open_trade["entry"], "exit": row["Close"],
            "gross_pips": gross, "profit": gross - spread - 2 * costs["slippage_pips"], "reason": "rebalance",
        })
        store["open_trade"][symbol] = None
    if new_side != 0:
        store["open_trade"][symbol] = {"side": new_side, "entry": row["Close"], "entry_date": pd.Timestamp(trade_date)}

def initialise_store(series):
    return {
        "month":        None,                         # month of the last bar seen
        "closes":       {s: [] for s in series},      # daily closes (mid)
        "open_trade":   {s: None for s in series},    # current leg, for the trade list
        "trade_list":   {s: [] for s in series},
        "last_ranking": None,
    }
