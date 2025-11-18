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

from src.trading.data.data_analysis.momentum_analysis import get_momentum_statistics, get_momentum_direction
from src.trading.data.data_analysis.analysis import is_momentum
from src.trading.data.data_analysis.volatility_analysis import get_volatility_statistics
from src.trading.risk_management.trade_record_management import TradeRecords
from src.trading.risk_management.stop_losses import fixed_stop_loss
from src.trading.risk_management.take_profit import fixed_take_profit

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
    momentum_score_thresh = 75,
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
    pos_size = 1 # -> CHANGE THIS
    holding_duration = 10 # CHANGE THIS TOO
    num_series = len(series)
    market      = [0] * num_series
    limit1      = [0] * num_series
    limit2      = [0] * num_series
    limitprice1 = [0] * num_series
    limitprice2 = [0] * num_series

    if store["iter"] >= minimum_data_points:
        for i, (symbol, row) in enumerate(zip(series, new_row_list)):
            if store["pending_trades"][symbol] != 0:
                store["trade_records"][symbol].add_new_trade_record(
                    asset=symbol,
                    time_frame=timeframe,
                    date=store["ohlcv"][symbol].index[-2],
                    pos_size=pos_size,
                    trade_type= "Buy" if store["pending_trades"][symbol] == 1 else "Sell", # Must be a sell if its not a buy
                    take_profit=fixed_take_profit(store["pending_trades"][symbol], row["Open"]),
                    stop_loss=fixed_stop_loss(store["pending_trades"][symbol], row["Open"]),
                    holding_duration=holding_duration,
                    normalised_score=store["pending_normalised_score"][symbol],
                    volatiltiy_indicator=0,  # NEED TO ADD THIS FUNCTIONALITY AND THE BELOWS
                    rsi=0,
                    moving_average_type=0,
                    moving_average_value=0
                )

            store, should_trade, normalised_score = analyse_momentum(
                store, symbol, params, timeframe, date,
                trade_high_volatility=False,
                trade_w_volatility=True
            )

            if should_trade:
                store["current_momentum_periods"][symbol].append(len(store["ohlcv"][symbol]) - 1)  # If momentum has been found, update the store to shown this
                market[i] = pos_size

                if len(store["current_momentum_periods"][symbol]) > 2:
                    start = store["current_momentum_periods"][symbol][0]
                    end = store["current_momentum_periods"][symbol][-1]

                    df_slice = store["ohlcv"][symbol].iloc[start:end + 1]

                    direction, net_ret = get_momentum_direction(df_slice)
                    if direction == 1 and normalised_score > momentum_score_thresh:    # Buy if direction is trending upwards and momentum score threshold is reached
                        print(f"BUY SIGNAL. Normalised score: {normalised_score}")
                        market[i] = pos_size
                        store["pending_trades"][symbol] = 1
                        store["pending_normalised_score"][symbol] = normalised_score
                    elif direction == -1 and normalised_score > momentum_score_thresh: # Sell if direction is trending downwards and momentum score threshold is reached
                        print(f"SELL SIGNAL. Normalised score: {normalised_score}")
                        store["pending_trades"][symbol] = -1
                        store["pending_normalised_score"][symbol] = normalised_score
                    else:
                        store["pending_trades"][symbol] = 0 # As momentum threshold has not been reached, reset pending trades as there are none
                        store["pending_normalised_score"][symbol] = 0

            else:
                if store["current_momentum_periods"][symbol]: # If there have been any periods of momentum
                    store["previous_momentum_periods"][symbol].append(
                        store["current_momentum_periods"][symbol]
                    )
                    store["current_momentum_periods"][symbol] = [] # Empty current momentum periods as non momentum is currently being exhibited
                store["pending_trades"][symbol] = 0 # As no momentum found, reset pending trades as there are none
                store["pending_normalised_score"][symbol] = 0

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

    momentum_found, normalised_score = is_momentum(momentum_stats, volatility_stats, trade_high_volatility=trade_high_volatility, trade_w_volatility=trade_w_volatility)

    return store, momentum_found, normalised_score

def initialise_store(series, default_lookback=20):
    cols = ["Open", "High", "Low", "Close", "Volume"]
    empty_idx = pd.DatetimeIndex([], name="Time")  # ← no tz

    return {
        "iter":            0,
        "ohlcv":           {s: pd.DataFrame(columns=cols, index=empty_idx.copy()) for s in series},
        "trade_records":   {s: TradeRecords() for s in series},
        "trade_histories": {s: {"wins": [], "losses": []} for s in series},
        "lookbacks":       {s: default_lookback for s in series},
        "strategy_on":     {s: True  for s in series},
        "win_prob":        {s: 0.0   for s in series},
        "win_loss_ratio":  {s: 0.0   for s in series},
        "count":           {s: 0     for s in series},
        "momentum_score":  {s: 0 for s in series},
        "volatility_score": {s: 0 for s in series},
        "current_momentum_periods": {s: [] for s in series},
        "previous_momentum_periods": {s: [] for s in series},
        "pending_normalised_score": {s: [] for s in series},
        "pending_trades": {s: [] for s in series}
    }

def update_store(store, new_row_list, series):
    store["iter"] += 1
    for s, row in zip(series, new_row_list): # Combines the series name with the new row list ohlcv values
        t = row["Time"]  # timestamp for this new OHLCV bar
        store["ohlcv"][s].loc[t] = [
            row["Open"], row["High"], row["Low"], row["Close"], row["Volume"]
        ]

    return store





