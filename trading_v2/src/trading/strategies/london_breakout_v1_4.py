# London Breakout v1.4 (USD_JPY, H1 bars, all times in London time)
# v1.4 = v1.3 (trend filter, 0.5% risk, no trades on NFP/CPI/FOMC days) + entry buffer (rule 7).
#
# Idea:
# Tokyo trading (00:00-07:00 London) is usually quiet, so price stays in a narrow range. When London opens,
# volume jumps and price often breaks out of that range and keeps going in the same direction for the day.
# The research notebook (london_breakout_jpy.ipynb) found a small edge of about +1.2 to +1.8 pips per trade
# after costs on USD_JPY, in every period tested.
#
# Rules:
# 1. Asian range: the highest high and lowest low of the bars from 00:00 to 07:00 London.
# 2. Entry: from 07:00 to 16:00, place a buy stop at the range high and a sell stop at the range low.
#    Whichever is hit first is the trade. Cancel the other order. One trade per day at most.
# 3. Stop loss: the other side of the range (a buy's stop is at the range low, a sell's stop at the range high).
# 4. Exit: if the stop has not been hit, close the trade at 20:00 London. No take-profit.
# 5. Position size: risk 0.5% of the account per trade, using the distance from entry to stop.
# 6. Trend filter: buy only if yesterday's close is above its trend_ma_days-day average, sell only if below.
#    trend_ma_type: "sma" (simple average) or "ema" (exponential, reacts faster).
#    No trades until there are enough daily closes for the average.
# 7. Entry buffer: the buy stop goes entry_buffer_pips above the range high (sell stop the same below the low),
#    so small pokes through the range don't trigger a trade. The stop loss stays at the other side of the range.
#    entry_buffer_pips: 0 turns it off (same as v1.3).
#
# Costs (set in the config): spread + 0.003% commission per side + 0.3 pips slippage on stop and market fills.
#
# Data rules: refine on 2005-2018 only. Rules get frozen before any other test.
import pandas as pd
import os
import trading.utils.constants as constants
from trading.utils.logger import info, warning

def generate_units(balance, risk_pct, entry, stop, price):
    # Units so that hitting the stop loses risk_pct % of the balance (USD_JPY: P&L is in yen, so convert with the price)
    risk_usd = balance * risk_pct / 100
    loss_per_unit_usd = abs(entry - stop) / price
    if loss_per_unit_usd == 0:
        return 0
    return int(risk_usd / loss_per_unit_usd)

def london_breakout_v1_4(store, new_row_list, current_pos, account_info, params):
    series = params["pairs"]

    # Initialise store if needed
    if store is None:
        store = initialise_store(series, params)

    # Update store with the *previous* bar per series
    store = update_store(store, new_row_list, series)
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

        london_time = row["Time"].tz_localize("UTC").tz_convert("Europe/London")
        hour = london_time.hour

        # New day: reset the range
        if london_time.date() != store["todays_date"][symbol]:
            store["news_day"][symbol] = london_time.date() in store["news_dates"]
            store["todays_date"][symbol] = london_time.date()
            store["asian_high"][symbol] = None
            store["asian_low"][symbol] = None
            store["asian_bars_seen"][symbol] = 0
            store["traded_today"][symbol] = False

            # Trend filter: yesterday's close vs the trend_ma_days average of daily closes (simple or exponential)
            if len(store["ohlcv"][symbol]) >= 2:
                store["daily_closes"][symbol].append(store["ohlcv"][symbol]["Close"].iloc[-2])   # last bar of yesterday
            closes = store["daily_closes"][symbol]
            n = params["trend_ma_days"]
            if len(closes) >= n:
                if params.get("trend_ma_type", "sma") == "ema":
                    average = pd.Series(closes).ewm(span=n, adjust=False).mean().iloc[-1]   # recent days count more
                else:
                    average = sum(closes[-n:]) / n                                          # every day counts the same
                store["trend"][symbol] = 1 if closes[-1] > average else -1

        # 00:00 to 06:00 bars: build the range
        if params["asian_start"] <= hour < params["asian_end"]:
            if store["asian_high"][symbol] is None or row["High"] > store["asian_high"][symbol]:
                store["asian_high"][symbol] = row["High"]
            if store["asian_low"][symbol] is None or row["Low"] < store["asian_low"][symbol]:
                store["asian_low"][symbol] = row["Low"]
            store["asian_bars_seen"][symbol] += 1

        # Range complete, and sending now means filling in the 07:00-15:00 bars (as in the notebook)
        range_ready = store["asian_bars_seen"][symbol] == params["asian_end"] - params["asian_start"]
        in_window = params["asian_end"] - 1 <= hour < params["last_entry_time"] - 1

        # Entry levels: the range plus the buffer
        pip = 0.01 if "JPY" in symbol else 0.0001
        buffer = params["entry_buffer_pips"] * pip
        if range_ready:
            buy_level = store["asian_high"][symbol] + buffer
            sell_level = store["asian_low"][symbol] - buffer

        # A stop filled on the last bar: remember the trade
        if current_pos[i] != 0 and store["trade_side"][symbol] == 0:
            store["trade_side"][symbol] = 1 if current_pos[i] > 0 else -1
            store["traded_today"][symbol] = True
            if store["trade_side"][symbol] == 1:
                store["stop_price"][symbol] = store["asian_low"][symbol]     # long: stop at the other side
                store["entry_price"][symbol] = max(row["Open"], buy_level)
            else:
                store["stop_price"][symbol] = store["asian_high"][symbol]    # short: stop at the other side
                store["entry_price"][symbol] = min(row["Open"], sell_level)
            store["entry_time"][symbol] = london_time

        # The trade closed on the last bar (stop hit or 20:00 exit): record it
        if current_pos[i] == 0 and store["trade_side"][symbol] != 0:
            side = store["trade_side"][symbol]
            if store["exit_sent"][symbol]:                       # closed by the 20:00 market order
                exit_price, reason = row["Open"], f"{params['exit_hour']}:00"
            else:                                                # stopped out (or gapped through the stop)
                stop = store["stop_price"][symbol]
                exit_price = min(row["Open"], stop) if side == 1 else max(row["Open"], stop)
                reason = "stop"
            gross_pips = side * (exit_price - store["entry_price"][symbol]) / 0.01
            store["trade_list"][symbol].append({
                "asset": symbol,                                 # column names match metrics_report
                "time_frame": params["timeframe"],
                "entry_date": store["entry_time"][symbol].tz_localize(None),   # London time, no timezone (metrics_report needs one format)
                "exit_date": london_time.tz_localize(None),
                "side": side,
                "entry": store["entry_price"][symbol],
                "exit": exit_price,
                "gross_pips": gross_pips,
                "profit": gross_pips - round_trip_cost_pips(symbol, store["entry_price"][symbol], params["costs"]),
                "reason": reason,
            })
            store["trade_side"][symbol] = 0
            store["exit_sent"][symbol] = False

        # Flat, range complete, in the entry window: send both entry stops (again, every bar)
        if current_pos[i] == 0 and range_ready and in_window and not store["traded_today"][symbol] and not store["news_day"][symbol]:
            if store["trend"][symbol] == 1:                      # uptrend: buy breakouts only
                units = generate_units(account_info["balance"], params["risk_per_trade"], buy_level,
                                       store["asian_low"][symbol], row["Close"])
                stop1[i] = units
                stop_price1[i] = buy_level
            elif store["trend"][symbol] == -1:                   # downtrend: sell breakouts only
                units = generate_units(account_info["balance"], params["risk_per_trade"], store["asian_high"][symbol],
                                       sell_level, row["Close"])
                stop2[i] = -units
                stop_price2[i] = sell_level

        # In a trade
        elif current_pos[i] != 0:
            # 19:00 bar: close at the 20:00 open. Also close if the 19:00 bar was missing (holidays, early closes)
            # and the trade is still open later that evening or on the next day
            if hour >= params["exit_hour"] - 1 or london_time.date() != store["entry_time"][symbol].date():
                market[i] = -current_pos[i]
                store["exit_sent"][symbol] = True
            elif current_pos[i] > 0:                              # long: protective sell stop
                stop2[i] = -current_pos[i]
                stop_price2[i] = store["stop_price"][symbol]
            else:                                                 # short: protective buy stop
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

def round_trip_cost_pips(symbol, price, costs):
    # Same costs the backtester charges: half the spread + commission + slippage, on entry and on exit
    pip = 0.01 if "JPY" in symbol else 0.0001
    spread = costs["spread_pips"].get(symbol, costs["spread_pips"].get("default", 0.0))
    commission = costs["commission_pct"] / 100 * price / pip
    return 2 * (spread / 2 + commission + costs["slippage_pips"])

def load_news_dates(events):
    macro = pd.read_csv(os.path.join(constants.DATA_DIR, "macro_dates.csv"))
    fomc = pd.read_csv(os.path.join(constants.DATA_DIR, "fomc_dates.csv")).assign(event="FOMC")
    news = pd.concat([macro, fomc])
    news = news[news["event"].isin(events)]
    return set(pd.to_datetime(news["date"]).dt.date)

def initialise_store(series, params):
    cols = ["Open", "High", "Low", "Close", "Volume"]
    empty_idx = pd.DatetimeIndex([], name="Time", tz="Europe/London")

    return {
        "iter":            0,
        "ohlcv":           {s: pd.DataFrame(columns=cols, index=empty_idx.copy()) for s in series},
        "news_dates":      load_news_dates(params["skip_news"]),
        "news_day":        {s: False for s in series},
        "todays_date":     {s: None  for s in series},   # London date of the current day
        "asian_high":      {s: None  for s in series},
        "asian_low":       {s: None  for s in series},
        "asian_bars_seen": {s: 0     for s in series},   # need all 7 (00:00-06:00) for a valid range
        "traded_today":    {s: False for s in series},
        "trade_side":      {s: 0     for s in series},   # +1 long, -1 short, 0 flat
        "entry_price":     {s: None  for s in series},
        "entry_time":      {s: None for s in series},
        "stop_price":      {s: None  for s in series},
        "exit_sent":       {s: False for s in series},   # market exit sent, so the next close is the time exit
        "trade_list":      {s: []    for s in series},   # one dict per finished trade
        "daily_closes":    {s: []    for s in series},   # one close per London day, for the trend filter
        "trend":           {s: 0     for s in series},   # +1 up, -1 down, 0 not enough data yet
    }

def update_store(store, new_row_list, series):
    store["iter"] += 1
    for s, row in zip(series, new_row_list):  # one new bar per pair
        london_time = row["Time"].tz_localize("UTC").tz_convert("Europe/London")
        store["ohlcv"][s].loc[london_time] = [
            row["Open"], row["High"], row["Low"], row["Close"], row["Volume"]
        ]
    return store



