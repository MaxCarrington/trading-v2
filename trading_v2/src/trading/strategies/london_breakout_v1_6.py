# London Breakout v1.6 (USD_JPY, H1 bars, all times in London time)
# v1.6 = v1.5 + rule 8, a daily regime filter. The edge only showed up in strongly trending, volatile years
# (2012-15, 2022) and leaked money in quiet years, so v1.6 only trades when the daily market is "moving":
#   regime_filter: "none"           -> same as v1.5
#   regime_filter: "atr_ratio"      -> trade only if the 20-day daily ATR / the regime_long_days ATR >= regime_min
#                                      (volatility is above its normal level)
#   regime_filter: "trend_strength" -> trade only if |yesterday's close - regime_long_days SMA| / 20-day ATR >= regime_min
#                                      (price is far from its long average, i.e. a strong trend)
# The filter only uses finished days, and no trades until there are regime_long_days days of history.
# Rule 9, range-width filter: compare today's Asian range with the median of the last 20 Asian ranges.
#   Skip the day if range / median < range_min_ratio (too narrow: noise) or > range_max_ratio
#   (too wide: the move already happened and the stop is far away). 0 turns each side off.
# v1.5 = v1.4 with real bid/ask fills: same rules, but with the config's costs model "bid_ask" every buy fills at
# OANDA's ask and every sell at its bid, so the trade list shows the real spread paid instead of an assumed one.
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
# Costs (set in the config): model "bid_ask" = buy at the ask, sell at the bid, plus commission per side and
# slippage on stop and market fills. Model "intraday" = mid prices plus an assumed spread (same as v1.4).
# The Asian range and the order levels are worked out on mid prices; buy stops trigger on the ask, sell stops on the bid.
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

def open_price(row, buying):
    # Price a market or gapped order fills at on this bar: the ask for a buy, the bid for a sell (mid if no bid/ask data)
    if "AskOpen" in row:
        return row["AskOpen"] if buying else row["BidOpen"]
    return row["Open"]

def london_breakout_v1_6(store, new_row_list, current_pos, account_info, params):
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
            store["range_checked"][symbol] = False

            # Trend filter: yesterday's close vs the trend_ma_days average of daily closes (simple or exponential)
            if len(store["ohlcv"][symbol]) >= 2:
                store["daily_closes"][symbol].append(store["ohlcv"][symbol]["Close"].iloc[-2])   # last bar of yesterday
                if store["day_high"][symbol] is not None:
                    store["daily_highs"][symbol].append(store["day_high"][symbol])
                    store["daily_lows"][symbol].append(store["day_low"][symbol])
            store["regime_ok"][symbol] = regime_ok(store, symbol, params)
            # today's high/low start with this bar (it is the first bar of the new day)
            store["day_high"][symbol] = row["High"]
            store["day_low"][symbol] = row["Low"]
            closes = store["daily_closes"][symbol]
            n = params["trend_ma_days"]
            if len(closes) >= n:
                if params.get("trend_ma_type", "sma") == "ema":
                    average = pd.Series(closes).ewm(span=n, adjust=False).mean().iloc[-1]   # recent days count more
                else:
                    average = sum(closes[-n:]) / n                                          # every day counts the same
                store["trend"][symbol] = 1 if closes[-1] > average else -1

        else:
            store["day_high"][symbol] = max(store["day_high"][symbol], row["High"])
            store["day_low"][symbol] = min(store["day_low"][symbol], row["Low"])

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

        # Rule 9: once the range is complete, check its width against recent days (then remember it)
        if range_ready and not store["range_checked"][symbol]:
            width = store["asian_high"][symbol] - store["asian_low"][symbol]
            store["range_ok"][symbol] = range_width_ok(width, store["asian_ranges"][symbol], params)
            store["asian_ranges"][symbol].append(width)
            store["range_checked"][symbol] = True

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
                store["entry_price"][symbol] = max(open_price(row, buying=True), buy_level)
            else:
                store["stop_price"][symbol] = store["asian_high"][symbol]    # short: stop at the other side
                store["entry_price"][symbol] = min(open_price(row, buying=False), sell_level)
            store["entry_time"][symbol] = london_time

        # The trade closed on the last bar (stop hit or 20:00 exit): record it
        if current_pos[i] == 0 and store["trade_side"][symbol] != 0:
            side = store["trade_side"][symbol]
            if store["exit_sent"][symbol]:                       # closed by the 20:00 market order
                exit_price, reason = open_price(row, buying=(side == -1)), f"{params['exit_hour']}:00"
            else:                                                # stopped out (or gapped through the stop)
                stop = store["stop_price"][symbol]
                exit_price = min(open_price(row, buying=False), stop) if side == 1 else max(open_price(row, buying=True), stop)
                reason = "stop"
            gross_pips = side * (exit_price - store["entry_price"][symbol]) / 0.01   # bid_ask model: spread already included
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
        if current_pos[i] == 0 and range_ready and in_window and not store["traded_today"][symbol] and not store["news_day"][symbol] \
                and store["regime_ok"][symbol] and store["range_ok"][symbol]:
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

def regime_ok(store, symbol, params):
    # rule 8: is the daily market moving enough to trade today? (uses finished days only)
    kind = params.get("regime_filter", "none")
    if kind == "none":
        return True
    highs, lows, closes = store["daily_highs"][symbol], store["daily_lows"][symbol], store["daily_closes"][symbol]
    n_long = params["regime_long_days"]
    if len(highs) < n_long + 1 or len(closes) < n_long + 1:
        return False
    # daily true range: the day's range, including any gap from the previous close
    h = pd.Series(highs[-(n_long + 1):])
    l = pd.Series(lows[-(n_long + 1):])
    c_prev = pd.Series(closes[-(n_long + 2):-1]) if len(closes) >= n_long + 2 else pd.Series(closes[-(n_long + 1):]).shift(1)
    c_prev.index = h.index
    true_range = pd.concat([h - l, (h - c_prev).abs(), (l - c_prev).abs()], axis=1).max(axis=1).iloc[1:]
    atr_short = true_range.iloc[-20:].mean()
    if atr_short == 0:
        return False
    if kind == "atr_ratio":
        return atr_short / true_range.mean() >= params["regime_min"]
    if kind == "trend_strength":
        average = sum(closes[-n_long:]) / n_long
        return abs(closes[-1] - average) / atr_short >= params["regime_min"]
    raise ValueError(f"Unknown regime_filter {kind}")

def range_width_ok(width, past_ranges, params):
    # rule 9: today's Asian range vs the median of the last 20
    low, high = params.get("range_min_ratio", 0), params.get("range_max_ratio", 0)
    if low == 0 and high == 0:
        return True
    if len(past_ranges) < 20:
        return False
    ratio = width / pd.Series(past_ranges[-20:]).median()
    if low and ratio < low:
        return False
    if high and ratio > high:
        return False
    return True

def round_trip_cost_pips(symbol, price, costs):
    # Same costs the backtester charges: half the spread + commission + slippage, on entry and on exit
    # (bid_ask model: the spread is already in the fill prices, so only commission + slippage)
    pip = 0.01 if "JPY" in symbol else 0.0001
    if costs["model"] == "bid_ask":
        spread = 0.0
    else:
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
        "daily_highs":     {s: []    for s in series},   # one high/low per London day, for the regime filter
        "daily_lows":      {s: []    for s in series},
        "day_high":        {s: None  for s in series},   # today's high/low so far
        "day_low":         {s: None  for s in series},
        "regime_ok":       {s: False for s in series},   # rule 8: today's regime allows trading
        "asian_ranges":    {s: []    for s in series},   # rule 9: past Asian range widths
        "range_checked":   {s: False for s in series},   # today's width already checked
        "range_ok":        {s: False for s in series},   # rule 9: today's width allows trading
    }

def update_store(store, new_row_list, series):
    store["iter"] += 1
    for s, row in zip(series, new_row_list):  # one new bar per pair
        london_time = row["Time"].tz_localize("UTC").tz_convert("Europe/London")
        store["ohlcv"][s].loc[london_time] = [
            row["Open"], row["High"], row["Low"], row["Close"], row["Volume"]
        ]
    return store



