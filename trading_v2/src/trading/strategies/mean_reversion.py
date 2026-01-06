import pandas as pd
from ta.volatility import BollingerBands
from src.trading.risk_management.trade_record_management import TradeRecords
from src.trading.data.data_analysis.mean_rev_analysis import get_series_mean_rev_stats

def units_from_capital(price, balance, frac=0.02, lot=1):
    if price <= 0 or balance <= 0 or frac <= 0: return 0
    units = int((balance * frac) // price)
    return max(units - (units % lot), 0)

def to_target_units(target, current):
    return int(target - current)

def _empty_ohlcv_df():
    return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])

def init_store(series):
    return {
        "iter": 0,
        "ohlcv": {s: _empty_ohlcv_df() for s in series},
        "half_lives": {s: 0 for s in series},
        "strategy_on": {s: True for s in series},
        "trades": TradeRecords(),
    }

def update_store(store, new_rows, series):
    store["iter"] += 1
    for s in series:
        row = new_rows[s]
        df = row.to_frame().T if isinstance(row, pd.Series) else row.copy()
        store["ohlcv"][s] = pd.concat([store["ohlcv"][s], df], axis=0, ignore_index=False)
    return store

def calculate_bollinger_bands(hlc_df, lookback, std_dev):
    bb = BollingerBands(close=hlc_df["Close"], window=lookback, window_dev=std_dev)
    return pd.DataFrame({
        "upper_band": bb.bollinger_hband(),
        "middle_band": bb.bollinger_mavg(),
        "lower_band": bb.bollinger_lband(),
    }, index=hlc_df.index)

def run_strategy(store, new_row_list, current_pos, info, params):
    prompts_on = True
    limit_orders_on = True
    sell_all_on = False

    series_list = params["series"]
    num_series = len(series_list)

    # init store once
    if store is None:
        store = init_store(series_list)

    # update OHLCV with prev rows (your backtester passes prev rows)
    store = update_store(store, {s: new_row_list[i] for i, s in enumerate(series_list)}, series_list)
    trades = store["trades"]

    # outputs must be lists (len = num_series)
    pos            = [0] * num_series
    limit_orders1  = [0] * num_series
    limit_prices1  = [0.0] * num_series
    limit_orders2  = [0] * num_series
    limit_prices2  = [0.0] * num_series

    for i, series_id in enumerate(series_list):
        series_df = store["ohlcv"][series_id]
        if series_df.shape[0] < 2:
            continue

        # yesterday's close / today's open (today's open comes from new_row_list)
        y_close = series_df["Close"].iloc[-2]   # because we appended prev rows
        t_open  = new_row_list[i]["Open"]

        # half-life update cadence
        half_life = store["half_lives"].get(series_id, 0) or params["halfLives"][i]
        if store["iter"] % max(1, half_life * 2) == 0:
            mr = get_series_mean_rev_stats(series_df.iloc[:-1], series_id, params.get("timeFrame"), params.get("date"), params["pValueThreshMR"])
            store["strategy_on"][series_id] = mr["strategyOn"]
            if mr["strategyOn"] and mr["halfLife"] > 0:
                store["half_lives"][series_id] = int(round(mr["halfLife"]))
                half_life = store["half_lives"][series_id]

        # manage existing trades
        if limit_orders_on:
            trades.check_if_limit_price_hit(store, new_row_list, series_list, i, prompts_on)
        else:
            trades.update_entry_prices(store, new_row_list, series_list, i, position_size=0, prompts_on=prompts_on)
        trades.increment_holding_periods(store, i)
        trades.add_exit_price(store, i, new_row_list)
        adjust = trades.adjust_positions(store, i, half_life, position_size=0, todays_open=t_open, prompts_on=prompts_on)
        store = adjust["updated_store"]
        adj_pos = adjust["pos"]

        # signal + sizing (position-aware, capital-aware)
        clip = max(units_from_capital(t_open, info["balance"],
                                      getattr(trades, "kelly_fraction", lambda _=i: 0.02)(i)), 1)

        if store["strategy_on"][series_id] and store["iter"] > half_life:
            hlc = series_df[["High", "Low", "Close"]].iloc[:-1]
            bb = calculate_bollinger_bands(hlc, half_life, params["stdDev"])

            target = current_pos[i]
            if y_close < bb["lower_band"].iloc[-1]:
                # go more long
                target = current_pos[i] + clip
                if limit_orders_on:
                    # create a limit trade at entry price (you can change price logic)
                    trade = trades.create_trade_record(store, i, clip, t_open, "buy", True)
                    store = trade["store"]
                    limit_orders1[i] = clip
                    limit_prices1[i] = trade["limitPrice"]
                else:
                    adj_pos += to_target_units(target, current_pos[i])

            elif y_close > bb["upper_band"].iloc[-1]:
                # go more short
                target = current_pos[i] - clip
                if limit_orders_on:
                    trade = trades.create_trade_record(store, i, clip, t_open, "sell", True)
                    store = trade["store"]
                    limit_orders1[i] = -clip
                    limit_prices1[i] = trade["limitPrice"]
                else:
                    adj_pos += to_target_units(target, current_pos[i])

        # flatten when strategy turns off
        if not store["strategy_on"][series_id] and sell_all_on:
            adj_pos += to_target_units(0, current_pos[i])

        pos[i] = adj_pos

    return {
        "store": store,
        "marketOrders": pos,
        "limitOrders1": limit_orders1,
        "limitPrices1": limit_prices1,
        "limitOrders2": limit_orders2,
        "limitPrices2": limit_prices2,
    }
