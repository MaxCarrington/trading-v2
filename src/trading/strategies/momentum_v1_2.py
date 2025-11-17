# This file contains strategy implementation for version 1.2 of a momentum strategy.
# Analysis:
# This strategy identifies when a market is exhibiting momentum by checking whether past returns positively correlate
# with future returns. It searches for the optimal lookback and holding period that produce the strongest positive
# correlation. The system periodically re-evaluates the data: if momentum is present and volatility is low, the strategy
# stays active using the updated lookback; if volatility is high or momentum weakens, the strategy pauses and rechecks
# after two lookback periods. This adaptive approach targets momentum phases while minimizing exposure during choppy markets.
#
# Strategy:
# Momentum strategy using RSI and a moving average to confirm trend direction.
# A buy signal occurs when RSI is high (overbought), the MA trends upward, and the current open exceeds the previous close,
# indicating strong upward momentum. A sell signal occurs when RSI is low (oversold), the MA trends downward, and the open
# is below the previous close, signaling sustained downward momentum. Volatility is monitored to filter entries.

import pandas as pd
import sys

from src.trading.data.data_analysis.momentum_analysis import get_momentum_statistics
from src.trading.data.data_analysis.analysis import is_momentum
from src.trading.data.data_analysis.volatility_analysis import get_volatility_statistics

MINIMUM_DAYS_FOR_ANALYSIS = 100

def momentum_strategy_v1_2(
    store,
    new_row_list,
    current_pos,
    info,
    params,
    prompts=False,
    use_limit_orders=True,
    use_kelly=False,
    pos_size=1,
    no_orders=1,
    sell_all=False,
    minimum_data_points=100
):
    # Extract global values
    series = params["pairs"]  # list of symbols like ["EUR_USD", "GBP_USD"]
    timeframe = params["timeframe"]
    date = params["date"]

    # Initialise store if needed
    if store is None:
        store = initialise_store(series, params["lookback"])

    # Update store with the *previous* bar per series
    store = update_store(store, new_row_list, series)

    num_series = len(series)
    market      = [0] * num_series
    limit1      = [0] * num_series
    limit2      = [0] * num_series
    limitprice1 = [0] * num_series
    limitprice2 = [0] * num_series

    if store["iter"] >= minimum_data_points:
        for i, (symbol, row) in enumerate(zip(series, new_row_list)):
            store, should_trade = analyse_momentum(
                store, symbol, params, timeframe, date,
                trade_high_volatility=False,
                trade_w_volatility=True
            )

            if should_trade:
                market[i] = pos_size

                trade_record = {
                    "time": row["Time"],
                    "symbol": symbol,
                    "action": "BUY" if pos_size > 0 else "SELL",
                    "size": pos_size,
                    "price": row["Close"]
                }
                store["trade_records"][symbol].append(trade_record)

    return {
        "marketOrders":  market,
        "limitOrders1":  limit1,
        "limitPrices1":  limitprice1,
        "limitOrders2":  limit2,
        "limitPrices2":  limitprice2,
        "store": store,
    }


def analyse_momentum(store, symbol, params, timeframe, date, trade_high_volatility, trade_w_volatility, high_volatility_thresh = 70, low_volatility_thresh = 30):
    df = store["ohlcv"][symbol]
    momentum_stats = get_momentum_statistics(df, params['momentum_len_thresh'][symbol], symbol, timeframe, date)
    store["momentum_score"][symbol] = momentum_stats["normalised_score"]

    volatility_stats = get_volatility_statistics(df, params["lookback"][symbol], symbol, timeframe, date)

    momentum_found = is_momentum(momentum_stats, volatility_stats, trade_high_volatility=trade_high_volatility, trade_w_volatility=trade_w_volatility)

    return store, momentum_found

def initialise_store(series, default_lookback=20):
    cols = ["Open", "High", "Low", "Close", "Volume"]
    empty_idx = pd.DatetimeIndex([], name="Time")  # ← no tz

    return {
        "iter":            0,
        "ohlcv":           {s: pd.DataFrame(columns=cols, index=empty_idx.copy()) for s in series},
        "trade_records":   {s: [] for s in series},
        "trade_histories": {s: {"wins": [], "losses": []} for s in series},
        "lookbacks":       {s: default_lookback for s in series},
        "strategy_on":     {s: True  for s in series},
        "win_prob":        {s: 0.0   for s in series},
        "win_loss_ratio":  {s: 0.0   for s in series},
        "count":           {s: 0     for s in series},
        "momentum_score":  {s: 0 for s in series},
        "volatility_score": {s: 0 for s in series},
    }

def update_store(store, new_row_list, series):
    store["iter"] += 1
    for s, row in zip(series, new_row_list): # Combines the series name with the new row list ohlcv values
        t = row["Time"]  # timestamp for this new OHLCV bar
        store["ohlcv"][s].loc[t] = [
            row["Open"], row["High"], row["Low"], row["Close"], row["Volume"]
        ]

    return store





