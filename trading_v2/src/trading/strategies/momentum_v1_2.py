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

from trading.data.data_analysis.momentum_analysis import get_momentum_statistics, get_momentum_direction
from trading.data.data_analysis.analysis import is_momentum
from trading.data.data_analysis.volatility_analysis import get_volatility_statistics
from trading.indicators.average_true_range import calculate_rolling_atr
from trading.risk_management.trade_record_management import TradeRecords
from trading.risk_management.stop_losses import compute_stop_loss
from trading.risk_management.take_profit import compute_take_profit
from trading.indicators.moving_averages import calculate_moving_average
from trading.indicators.relative_strength_index import calculate_rsi, is_rsi_overbought, is_rsi_oversold

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
    series = params["pairs"]

    # Initialise store if needed
    if store is None:
        store = initialise_store(series, params["momentum_lookback"])

    # Update store with the *previous* bar per series
    store = update_store(store, new_row_list, series)
    num_series = len(series)
    market      = [0] * num_series
    limit1      = [0] * num_series
    limit2      = [0] * num_series
    limitprice1 = [0] * num_series
    limitprice2 = [0] * num_series

    prompts = False

    if store["iter"] >= minimum_data_points:
        for i, (symbol, row) in enumerate(zip(series, new_row_list)):

            timeframe = params["timeframe"]
            date = params["date"]
            rsi_lookback = params["rsi_lookback"][symbol]
            ma_lookback = params["ma_lookback"][symbol]
            ma_thresh = params["ma_thresh"][symbol]
            ma_type = params["ma_type"]
            overbought_thresh = params["overbought_thresh"][symbol]
            oversold_thresh = params["oversold_thresh"][symbol]
            momentum_score_thresh = params["momentum_score_thresh"][symbol]
            max_holding_duration = params["max_holding_duration"][symbol]

            # Close existing trades
            store["trade_records"][symbol].close_trade_records(
                todays_open=row["Open"],
                todays_spread=row["Spread"],
                todays_date=row["Time"].replace(tzinfo=None),
                prompts_on=prompts
            )

            # Adjust positions
            pos_adjustment = store["trade_records"][symbol].adjust_positions(
                todays_high=row["High"],
                todays_low=row["Low"]
            )
            market[i] += pos_adjustment

            # 3. Calculate indicators for this symbol
            close_series = store["ohlcv"][symbol]["Close"]
            ma_value = calculate_moving_average(ma_type, close_series, ma_lookback).iloc[-1]
            df = store["ohlcv"][symbol]
            atr_lookback = params.get("atr_lookback", 14)
            atr_series = calculate_rolling_atr(df, lookback=atr_lookback)

            # Store the latest ATR value so SL/TP functions can reach it
            if "atr_value" not in store:
                store["atr_value"] = {}
            store["atr_value"][symbol] = atr_series.iloc[-1]
            rsi_value = calculate_rsi(close_series, rsi_lookback).iloc[-1]

            store["pending_rsi_value"][symbol] = rsi_value
            store["pending_moving_average_value"][symbol] = ma_value

            # --- Phase 1: Execute pending trade at today's open ---
            if store["pending_trades"][symbol] != 0 and store["pending_entry_date"][symbol] is not None:
                store["trade_records"][symbol].add_new_trade_record(
                    asset=symbol,
                    time_frame=timeframe,
                    date=row["Time"].replace(tzinfo=None),  # when the signal was generated
                    entry_price=row["Open"],  # execution price
                    entry_spread=row["Spread"],
                    pos_size=pos_size,
                    trade_type="Buy" if store["pending_trades"][symbol] == 1 else "Sell",
                    take_profit=compute_take_profit(trade_type=store["pending_trades"][symbol],
                                            entry_price=row["Open"],
                                            params=params,
                                            atr_value=store.get("atr_value", {}).get(symbol)),
                    stop_loss=compute_stop_loss(trade_type=store["pending_trades"][symbol],
                                                entry_price=row["Open"],
                                                params=params,
                                                atr_value=store.get("atr_value", {}).get(symbol)),
                    max_holding_duration=max_holding_duration,
                    normalised_score=store["pending_normalised_score"][symbol],
                    combined_volatility_score=store["pending_combined_volatility_score"][symbol],
                    period_volatility_score=store["pending_period_volatility_score"][symbol],
                    stddev_volatility=store["pending_stddev_volatility_score"][symbol],
                    rsi= store["pending_rsi_value"][symbol],
                    overbought_thresh=overbought_thresh,
                    oversold_thresh=oversold_thresh,
                    moving_average_type= ma_type,
                    moving_average_value=store["pending_moving_average_value"][symbol],
                    moving_average_thresh=ma_thresh,
                )

                # Reset pending trade after execution
                store["pending_trades"][symbol] = 0
                store["pending_entry_date"][symbol] = None
                store["pending_normalised_score"][symbol] = 0

            # --- Phase 2: Detect new signals and mark pending trade for tomorrow ---
            store, should_trade, normalised_score, volatility_stats = analyse_momentum(
                store, symbol, params, timeframe, date,
                momentum_threshold=momentum_score_thresh,
                trade_high_volatility=False,
                trade_w_volatility=True
            )
            if should_trade:
                store["current_momentum_periods"][symbol].append(len(store["ohlcv"][symbol]) - 1)
                if len(store["current_momentum_periods"][symbol]) > 0:
                    start = store["current_momentum_periods"][symbol][0]
                    end = store["current_momentum_periods"][symbol][-1]

                    df_slice = store["ohlcv"][symbol].iloc[start:end + 1]
                    direction, net_ret = get_momentum_direction(df_slice)

                    entry_volatility_score = volatility_stats["combined_score"].iloc[-1]  # latest combined score
                    entry_volatility_period = volatility_stats["period_vol"][-1]  # latest categorical label
                    entry_volatility_stddev = volatility_stats["stddev"].iloc[-1]  # latest stddev value
                    if direction == 1 and normalised_score > momentum_score_thresh: # and is_rsi_oversold(rsi_value, oversold_thresh) and row["Open"] < ma_value:
                        print(f"BUY SIGNAL. Normalised score: {normalised_score}")
                        market[i] += pos_size
                        store["pending_trades"][symbol] = 1
                        store["pending_entry_date"][symbol] = row["Time"].replace(tzinfo=None)
                        store["pending_normalised_score"][symbol] = normalised_score
                        # Add temporary volatility information to the store to update a trade record with
                        store["pending_combined_volatility_score"][symbol] = entry_volatility_score
                        store["pending_period_volatility_score"][symbol] = entry_volatility_period
                        store["pending_stddev_volatility_score"][symbol] = entry_volatility_stddev

                    elif direction == -1 and normalised_score > momentum_score_thresh: # and is_rsi_overbought(rsi_value, overbought_thresh) and row["Open"] > ma_value:
                        print(f"SELL SIGNAL. Normalised score: {normalised_score}")
                        market[i] -= pos_size
                        store["pending_trades"][symbol] = -1
                        store["pending_entry_date"][symbol] = row["Time"].replace(tzinfo=None)
                        store["pending_normalised_score"][symbol] = normalised_score
                        # Add temporary volatility information to the store to update a trade record with
                        store["pending_combined_volatility_score"][symbol] = entry_volatility_score
                        store["pending_period_volatility_score"][symbol] = entry_volatility_period
                        store["pending_stddev_volatility_score"][symbol] = entry_volatility_stddev

                    else:
                        store["pending_trades"][symbol] = 0
                        store["pending_entry_date"][symbol] = None
                        store["pending_normalised_score"][symbol] = 0
                        store["pending_combined_volatility_score"][symbol] = 0
                        store["pending_period_volatility_score"][symbol] = ""
                        store["pending_stddev_volatility_score"][symbol] = 0

            else:
                if store["current_momentum_periods"][symbol]:
                    store["previous_momentum_periods"][symbol].append(store["current_momentum_periods"][symbol])
                    store["current_momentum_periods"][symbol] = []
                store["pending_trades"][symbol] = 0
                store["pending_entry_date"][symbol] = None
                store["pending_normalised_score"][symbol] = 0

    return {
        "marketOrders":  market,
        "limitOrders1":  limit1,
        "limitPrices1":  limitprice1,
        "limitOrders2":  limit2,
        "limitPrices2":  limitprice2,
        "store": store,
    }

def analyse_momentum(store, symbol, params, timeframe, start_date, end_date=None, trade_high_volatility=True, trade_w_volatility=True, momentum_threshold=70, high_volatility_thresh = 70, low_volatility_thresh = 30):
    df = store["ohlcv"][symbol]
    momentum_stats = get_momentum_statistics(df, params['momentum_len_thresh'][symbol], symbol, timeframe,start_date, end_date)
    store["momentum_score"][symbol] = momentum_stats["normalised_score"]

    volatility_stats = get_volatility_statistics(df, params["lookback"][symbol], symbol, timeframe, start_date, end_date)

    momentum_found, normalised_score = is_momentum(momentum_stats, volatility_stats, momentum_threshold, trade_high_volatility=trade_high_volatility, trade_w_volatility=trade_w_volatility)

    return store, momentum_found, normalised_score, volatility_stats

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
        "pending_trades": {s: [] for s in series},
        "pending_entry_date": {s: None for s in series},
        "pending_combined_volatility_score": {s: 0.0 for s in series},
        "pending_period_volatility_score": {s: "" for s in series},
        "pending_stddev_volatility_score": {s: 0.0 for s in series},
        "pending_rsi_value": {s: 0.0 for s in series},
        "pending_moving_average_value": {s: 0.0 for s in series},
    }

def update_store(store, new_row_list, series):
    store["iter"] += 1
    for s, row in zip(series, new_row_list): # Combines the series name with the new row list ohlcv values
        t = row["Time"]  # timestamp for this new OHLCV bar
        store["ohlcv"][s].loc[t] = [
            row["Open"], row["High"], row["Low"], row["Close"], row["Volume"]
        ]

    return store





