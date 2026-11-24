# Gold Donchian trend breakout v1.0 (XAU_USD, H1 bars, mid prices)
#
# Idea:
# Gold trends in bursts. When price breaks out of its range of the last few days, it often keeps going.
# We buy the breakout and let a trailing stop follow the move, so small losses pay for the occasional big trend.
# Research 2005-18: 1767 trades, +0.075% per trade after costs, t 2.97 (see the build guide).
#
# Rules:
# 1. Channel: the highest High and lowest Low of the last channel_bars bars (55 hours).
# 2. Entry (flat only): a buy stop at the channel high and a sell stop at the channel low. One trade at a time.
# 3. Starting stop: on the bar the trade fills, trail_atr x ATR (4 ATRs) behind that bar's High (long) or Low (short).
# 4. Trailing stop: every bar after that, the stop follows the best price since entry, trail_atr x ATR behind it.
#    It only ever moves in the trade's favour.
# 5. Exit: only the trailing stop. No take-profit, no time exit.
# ATR = the average true range of the atr_bars (14) bars BEFORE the current bar.
#
# Data rules: refine on 2005-2018 only. Rules get frozen before any other test.

def true_range(high, low, previous_close):
    # The bar's full move, including any gap from the previous close
    return max(high - low, abs(high - previous_close), abs(low - previous_close))

def gold_donchian_v1_0(store, new_row_list, current_pos, account_info, params):
    series = params["pairs"]
    channel_bars = params["channel_bars"]
    atr_bars = params["atr_bars"]
    trailing_atr = params["trail_atr"]

    # Initialise store if needed
    if store is None:
        store = initialise_store(series)

    num_series = len(series)
    market      = [0] * num_series
    limit1      = [0] * num_series
    limit2      = [0] * num_series
    limitprice1 = [0] * num_series
    limitprice2 = [0] * num_series
    stop1       = [0] * num_series   # buy stop (units)
    stop2       = [0] * num_series   # sell stop (units, negative)
    stop_price1 = [0] * num_series
    stop_price2 = [0] * num_series

    for i, (symbol, row) in enumerate(zip(series, new_row_list)):

        # ATR from the bars before this one (this bar is added to the history further down)
        true_ranges = store["true_ranges"][symbol]
        if len(true_ranges) >= atr_bars:
            atr_before_this_bar = sum(true_ranges[-atr_bars:]) / atr_bars
        else:
            atr_before_this_bar = None                  # not enough history yet

        # A stop entry filled on this bar: remember the trade and set the starting stop
        if current_pos[i] != 0 and store["trade_side"][symbol] == 0:
            if current_pos[i] > 0:                      # long
                store["trade_side"][symbol] = 1
                store["entry_price"][symbol] = max(row["Open"], store["buy_level"][symbol])    # gapped above = filled at the open
                store["best_price"][symbol] = row["High"]
                store["stop_price"][symbol] = row["High"] - trailing_atr * atr_before_this_bar
            else:                                       # short
                store["trade_side"][symbol] = -1
                store["entry_price"][symbol] = min(row["Open"], store["sell_level"][symbol])   # gapped below = filled at the open
                store["best_price"][symbol] = row["Low"]
                store["stop_price"][symbol] = row["Low"] + trailing_atr * atr_before_this_bar
            store["entry_time"][symbol] = row["Time"]

        # The trailing stop was hit on this bar: record the trade
        elif current_pos[i] == 0 and store["trade_side"][symbol] != 0:
            side = store["trade_side"][symbol]
            stop = store["stop_price"][symbol]
            if side == 1:
                exit_price = min(row["Open"], stop)     # gapped below the stop = filled at the open
            else:
                exit_price = max(row["Open"], stop)
            gross_pct = side * (exit_price / store["entry_price"][symbol] - 1) * 100
            store["trade_list"][symbol].append({
                "asset": symbol,                        # column names match metrics_report
                "time_frame": params["timeframe"],
                "entry_date": store["entry_time"][symbol],
                "exit_date": row["Time"],
                "side": side,
                "entry": store["entry_price"][symbol],
                "exit": exit_price,
                "gross_pips": gross_pct,
                "profit": gross_pct,                    # costs are charged by the backtester
                "reason": "trailing stop",
            })
            store["trade_side"][symbol] = 0

        # Still in the trade: move the trailing stop up (long) or down (short), never back
        elif current_pos[i] != 0:
            if store["trade_side"][symbol] == 1:
                store["best_price"][symbol] = max(store["best_price"][symbol], row["High"])
                new_stop = store["best_price"][symbol] - trailing_atr * atr_before_this_bar
                store["stop_price"][symbol] = max(store["stop_price"][symbol], new_stop)
            else:
                store["best_price"][symbol] = min(store["best_price"][symbol], row["Low"])
                new_stop = store["best_price"][symbol] + trailing_atr * atr_before_this_bar
                store["stop_price"][symbol] = min(store["stop_price"][symbol], new_stop)

        # Add this bar to the history
        store = update_store(store, symbol, row, channel_bars)

        # Flat with enough history: send both entry stops for the next bar (again every bar, the channel moves)
        enough_history = len(store["highs"][symbol]) >= channel_bars and len(store["true_ranges"][symbol]) >= atr_bars
        completed_days = store["daily_closes"][symbol][:-1]
        trend_days = params["trend_days"]
        if trend_days > 0 and len(completed_days) >= trend_days:
            trend_average = sum(completed_days[-trend_days:]) / trend_days
            uptrend = completed_days[-1] > trend_average
            downtrend = completed_days[-1] < trend_average
        else:
            uptrend = downtrend = (trend_days == 0)  # 0 = filter off, same as now

        if current_pos[i] == 0 and enough_history:
            store["buy_level"][symbol] = max(store["highs"][symbol][-channel_bars:])
            store["sell_level"][symbol] = min(store["lows"][symbol][-channel_bars:])
            # Risk sizing: losing the full stop distance costs risk_per_trade % of the balance
            if params["risk_per_trade"] > 0:
                stop_distance = trailing_atr * atr_before_this_bar
                smallest_stop = row["Close"] * params[
                    "min_stop_pct"] / 100  # very quiet hours give a tiny ATR, so set a floor
                stop_distance = max(stop_distance, smallest_stop)
                units = account_info["balance"] * params["risk_per_trade"] / 100 / stop_distance
            else:
                units = params["position_size"]
            if uptrend:  # only buy breakouts above the 200-day average
                stop1[i] = units
                stop_price1[i] = store["buy_level"][symbol]
            if params["sides"] == "both" and downtrend:  # only sell breakouts below it
                stop2[i] = -units
                stop_price2[i] = store["sell_level"][symbol]

        # In a trade: send the protective trailing stop
        elif current_pos[i] > 0:                        # long: sell stop
            stop2[i] = -current_pos[i]
            stop_price2[i] = store["stop_price"][symbol]
        elif current_pos[i] < 0:                        # short: buy stop
            stop1[i] = -current_pos[i]
            stop_price1[i] = store["stop_price"][symbol]

    return {
        "marketOrders": market,
        "limitOrders1": limit1,
        "limitPrices1": limitprice1,
        "limitOrders2": limit2,
        "limitPrices2": limitprice2,
        "stopOrders1":  stop1,
        "stopPrices1":  stop_price1,
        "stopOrders2":  stop2,
        "stopPrices2":  stop_price2,
        "store": store,
    }

def initialise_store(series):
    return {
        "highs":       {s: [] for s in series},     # recent bar highs, for the channel
        "lows":        {s: [] for s in series},     # recent bar lows, for the channel
        "closes":      {s: [] for s in series},     # recent closes, for the true range
        "true_ranges": {s: [] for s in series},     # recent true ranges, for the ATR
        "trade_side":  {s: 0 for s in series},      # +1 long, -1 short, 0 flat
        "entry_price": {s: None for s in series},
        "entry_time":  {s: None for s in series},
        "best_price":  {s: None for s in series},   # highest High (long) / lowest Low (short) since entry
        "stop_price":  {s: None for s in series},   # the trailing stop
        "buy_level":   {s: None for s in series},   # channel high sent as the buy stop
        "sell_level":  {s: None for s in series},   # channel low sent as the sell stop
        "trade_list":  {s: [] for s in series},     # one dict per finished trade (read by run_backtest.py)
        "daily_closes": {s: [] for s in series},
        "current_day": {s: None for s in series},
    }

def update_store(store, symbol, row, channel_bars):
    closes = store["closes"][symbol]
    if closes:                                      # needs a previous close
        store["true_ranges"][symbol].append(true_range(row["High"], row["Low"], closes[-1]))
    store["highs"][symbol].append(row["High"])
    store["lows"][symbol].append(row["Low"])
    store["closes"][symbol].append(row["Close"])
    for key in ["highs", "lows", "closes", "true_ranges"]:          # keep only what the channel needs
        store[key][symbol] = store[key][symbol][-(channel_bars + 1):]
    day = row["Time"].date()
    if day != store["current_day"][symbol]:
        store["daily_closes"][symbol].append(row["Close"])  # first bar of a new day
        store["current_day"][symbol] = day
    else:
        store["daily_closes"][symbol][-1] = row["Close"]  # keep updating today's close
    store["daily_closes"][symbol] = store["daily_closes"][symbol][-201:]
    return store
