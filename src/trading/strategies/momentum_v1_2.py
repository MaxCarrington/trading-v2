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
        for symbol, row in zip(series, new_row_list):
            if store["iter"] >= MINIMUM_DAYS_FOR_ANALYSIS and store["iter"] >= store["next_momentum_check"][symbol]:
                store, should_trade = analyse_momentum(
                    store, symbol, params, timeframe, date,
                    trade_high_volatility=False,
                    trade_w_volatility=True
                )
                print(should_trade)

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
    momentum_window = get_momentum_window(df, store, symbol)
    momentum_stats = get_momentum_statistics(momentum_window, params['p-val_len_thresh'][symbol], symbol, timeframe, date)
    store["momentum_score"][symbol] = momentum_stats["normalised_score"]

    vol_window = get_volatility_window(df, store, symbol)
    volatility_stats = get_volatility_statistics(vol_window, params["lookback"][symbol], symbol, timeframe, date)
    vol_score = volatility_stats["combined_score"].iloc[-1]

    if vol_score <= low_volatility_thresh and trade_high_volatility == False and trade_w_volatility and not store["volatility_regime_active"][symbol]:
        store["volatility_regime_active"][symbol] = True
        store["volatility_regime_start_index"][symbol] = store["iter"]

    elif vol_score >= high_volatility_thresh and trade_high_volatility == True and trade_w_volatility and not store["volatility_regime_active"][symbol]:
        store["volatility_regime_active"][symbol] = True
        store["volatility_regime_start_index"][symbol] = store["iter"]

    elif vol_score >= high_volatility_thresh and trade_high_volatility and trade_w_volatility and store["volatility_regime_active"][symbol]:
        store["volatility_regime_active"][symbol] = False
        store["volatility_regime_end_index"][symbol] = store["iter"]
        store["volatility_regime_history"][symbol].append({
            "start": store["volatility_regime_start_index"][symbol],
            "end": store["iter"]
        })

    elif vol_score <= low_volatility_thresh and trade_high_volatility == False and trade_w_volatility and store["volatility_regime_active"][symbol]:
        store["volatility_regime_active"][symbol] = False
        store["volatility_regime_end_index"][symbol] = store["iter"]
        store["volatility_regime_history"][symbol].append({
            "start": store["volatility_regime_start_index"][symbol],
            "end": store["iter"]
        })

    momentum_found = is_momentum(momentum_stats, volatility_stats, trade_high_volatility, trade_w_volatility)

    if momentum_found and not store["regime_active"][symbol]:
        # New regime started
        store["regime_active"][symbol] = True
        store["regime_start_index"][symbol] = store["iter"]

    elif not momentum_found and store["regime_active"][symbol]:
        # Regime ended
        store["regime_active"][symbol] = False
        store["regime_end_index"][symbol] = store["iter"]
        store["regime_history"][symbol].append({
            "start": store["regime_start_index"][symbol],
            "end": store["iter"]
        })

    return store, momentum_found

def get_momentum_window(df, store, symbol, min_length=100, max_length=300):
    end = store["iter"]

    # If a regime just ended, use that window
    if "regime_end_index" in store and store["regime_end_index"][symbol] is not None:
        start = store["regime_end_index"][symbol] - min_length
        start = max(0, start)
        return df.iloc[start:end]

    # If a regime is active, use from start of regime to now
    if store["regime_active"][symbol]:
        start = store["regime_start_index"][symbol]
        if end - start >= min_length:
            return df.iloc[start:end]
        else:
            # Extend backward to meet min length
            start = max(0, end - min_length)
            return df.iloc[start:end]

    # No regime info — fallback to tail
    return df.iloc[-min(max_length, len(df)):]

def get_volatility_window(df, store, symbol, min_length=20, default_length=50):
    end = store["iter"]

    # If momentum is active, use regime start to now
    if store["regime_active"].get(symbol, False):
        start = store["regime_start_index"].get(symbol, 0)
        if end - start >= min_length:
            return df.iloc[start:end]
        else:
            return df.iloc[max(0, end - min_length):end]

    # If momentum just ended, use last regime window
    elif store.get("regime_end_index", {}).get(symbol) is not None:
        start = store["regime_start_index"].get(symbol, 0)
        end_regime = store["regime_end_index"][symbol]
        if end_regime - start >= min_length:
            return df.iloc[start:end_regime]
        else:
            return df.iloc[max(0, end_regime - min_length):end_regime]

    # Fallback: use tail slice
    return df.iloc[-default_length:]

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

        "regime_active":         {s: False for s in series},            # Tracks whether the symbol is currently in a momentum regime
        "regime_start_index":    {s: None for s in series},
        "regime_end_index":      {s: None for s in series},
        "regime_history":        {s: [] for s in series},
        "next_momentum_check":   {s: 0 for s in series},

        "volatility_regime_active": {s: False for s in series},
        "volatility_regime_start_index": {s: None for s in series},
        "volatility_regime_end_index": {s: None for s in series},
        "volatility_regime_history": {s: [] for s in series},

    }

def update_store(store, new_row_list, series):
    store["iter"] += 1
    for s, row in zip(series, new_row_list): # Combines the series name with the new row list ohlcv values
        t = row["Time"]  # timestamp for this new OHLCV bar
        store["ohlcv"][s].loc[t] = [
            row["Open"], row["High"], row["Low"], row["Close"], row["Volume"]
        ]

    return store





