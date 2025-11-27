import pandas as pd
import os
from datetime import datetime

from src.trading.risk_management import take_profit
from src.trading.risk_management.position_sizing import initialise_kelly

class TradeRecords:
    def __init__(self):
        self.trade_records = pd.DataFrame({
            "trade_id": pd.Series(dtype="int64"),
            "asset": pd.Series(dtype="string"),
            "time_frame": pd.Series(dtype="string"),
            "datetime": pd.Series(dtype="datetime64[ns]"),
            "entry_date": pd.Series(dtype="datetime64[ns]"),
            "exit_date": pd.Series(dtype="datetime64[ns]"),
            "entry_price": pd.Series(dtype="float64"),
            "exit_price": pd.Series(dtype="float64"),
            "entry_spread": pd.Series(dtype="float64"),   # NEW: spread at entry
            "exit_spread": pd.Series(dtype="float64"),    # NEW: spread at exit
            "spread_cost": pd.Series(dtype="float64"),    # NEW: cost due to spread
            "pos_size": pd.Series(dtype="float64"),
            "trade_type": pd.Series(dtype="string"),
            "is_limit": pd.Series(dtype="bool"),
            "take_profit": pd.Series(dtype="float64"),
            "stop_loss": pd.Series(dtype="float64"),
            "holding_duration": pd.Series(dtype="int32"),
            "max_holding_duration": pd.Series(dtype="float64"),
            "open": pd.Series(dtype="bool"),
            "closed": pd.Series(dtype="bool"),
            "cancelled": pd.Series(dtype="bool"),
            "pending_close": pd.Series(dtype="bool"),
            "pending_close_reason": pd.Series(dtype="string"),
            "profit": pd.Series(dtype="float64"),
            "normalised_score": pd.Series(dtype="float64"),
            "combined_volatility_score": pd.Series(dtype="float64"),
            "period_volatility_score": pd.Series(dtype="float64"),
            "stddev_volatility_score": pd.Series(dtype="float64"),
            "rsi": pd.Series(dtype="float64"),
            "overbought_thresh": pd.Series(dtype="float64"),
            "oversold_thresh": pd.Series(dtype="float64"),
            "moving_average_type": pd.Series(dtype="string"),
            "moving_average_value": pd.Series(dtype="float64"),
            "moving_average_thresh": pd.Series(dtype="float64"),
        })
        self.kelly_sizers = {}
        self.trade_index = 0

    def add_new_trade_record(self, asset, time_frame, date, pos_size,
                             trade_type, take_profit, stop_loss, max_holding_duration,
                             normalised_score, combined_volatility_score, period_volatility_score, stddev_volatility,
                             rsi, overbought_thresh, oversold_thresh, moving_average_type, moving_average_value, moving_average_thresh,
                             entry_date=None, entry_price=None, limitPrice=None, entry_spread=None):
        # Create a new trade record with all required information about a trade
        self.trade_index += 1
        new_trade = {
            "trade_id": self.trade_index,
            "asset": asset,
            "time_frame": time_frame,
            "datetime": pd.to_datetime(date),
            "entry_date": pd.to_datetime(entry_date) if entry_date is not None else pd.to_datetime(date),
            "exit_date": None,
            "entry_price": entry_price if entry_price is not None else (limitPrice if limitPrice is not None else None),
            "exit_price": None,
            "entry_spread": entry_spread,
            "exit_spread": None,
            "spread_cost": 0.0,
            "pos_size": pos_size,
            "trade_type": trade_type,
            "is_limit": limitPrice is not None,
            "take_profit": take_profit,
            "stop_loss": stop_loss,
            "holding_duration": 0,
            "max_holding_duration": max_holding_duration,
            "open": True,
            "closed": False,
            "cancelled": False,
            "pending_close": False,
            "pending_close_reason": None,
            "profit": 0.0,
            "normalised_score": normalised_score,
            "combined_volatility_score": combined_volatility_score,
            "period_volatility_score": period_volatility_score,
            "stddev_volatility_score": stddev_volatility,
            "rsi": rsi,
            "overbought_thresh": overbought_thresh,
            "oversold_thresh": oversold_thresh,
            "moving_average_type": moving_average_type,
            "moving_average_value": moving_average_value,
            "moving_average_thresh": moving_average_thresh,
        }

        # Add the new trade record to the data frame of trade records
        self.trade_records = pd.concat(
            [self.trade_records, pd.DataFrame([new_trade])],
            ignore_index=True
        )

    # Detect exit conditions for open trades (stop-loss, take-profit, max holding duration).
    # Mark trades as pending_close today, but and pass a position adjustment to close trade
    def adjust_positions(self, todays_high, todays_low):
        pos_adjustment = 0

        for idx, trade in self.trade_records[self.trade_records["open"]].iterrows():
            # Increment holding duration
            self.trade_records.at[idx, "holding_duration"] += 1

            trade_type = 1 if trade["trade_type"] == "buy" else -1
            pos_size = trade["pos_size"]

            # Take-profit detection
            if (trade_type == 1 and todays_high >= trade["take_profit"]) or \
                    (trade_type == -1 and todays_low <= trade["take_profit"]):
                self.trade_records.at[idx, "pending_close"] = True
                self.trade_records.at[idx, "pending_close_reason"] = "take_profit"
                pos_adjustment += -pos_size if trade_type == 1 else pos_size

            # Stop-loss detection
            if (trade_type == 1 and todays_low <= trade["stop_loss"]) or \
                    (trade_type == -1 and todays_high >= trade["stop_loss"]):
                self.trade_records.at[idx, "pending_close"] = True
                self.trade_records.at[idx, "pending_close_reason"] = "stop_loss"
                pos_adjustment += -pos_size if trade_type == 1 else pos_size

            # Max holding duration detection
            if self.trade_records.at[idx, "holding_duration"] >= trade["max_holding_duration"]:
                self.trade_records.at[idx, "pending_close"] = True
                self.trade_records.at[idx, "pending_close_reason"] = "max_hold"
                pos_adjustment += -pos_size if trade_type == 1 else pos_size

        return pos_adjustment

    # Execute closure of trades flagged as pending_close.
    # Called at the start of each iteration, before adjust_positions.
    def close_trade_records(self, todays_open, todays_spread, todays_date, prompts_on=False):
        for idx, trade in self.trade_records[self.trade_records["pending_close"]].iterrows():
            self.trade_records.at[idx, "exit_price"] = todays_open
            self.trade_records.at[idx, "exit_date"] = todays_date
            self.trade_records.at[idx, "exit_spread"] = todays_spread
            self.trade_records.at[idx, "open"] = False
            self.trade_records.at[idx, "closed"] = True
            self.trade_records.at[idx, "pending_close"] = False

            # Direction
            trade_type = 1 if trade["trade_type"] == "buy" else -1
            entry_price = trade["entry_price"]
            pos_size = trade["pos_size"]

            # 1) Gross PnL on mid prices
            if trade_type == 1:
                gross = (todays_open - entry_price) * pos_size
            else:
                gross = (entry_price - todays_open) * pos_size

            # 2) Spread cost: approx pay 1/2 spread at entry + 1/2 at exit
            entry_spread = trade["entry_spread"]
            if pd.isna(entry_spread):
                entry_spread = todays_spread  # fallback if missing

            avg_spread = 0.5 * (entry_spread + todays_spread)
            spread_cost = avg_spread * abs(pos_size)
            print("SPREAD COST: ", spread_cost)
            # 3) Net profit
            profit = gross - spread_cost

            self.trade_records.at[idx, "spread_cost"] = spread_cost
            self.trade_records.at[idx, "profit"] = profit

            if prompts_on:
                print(
                    f"Closed {trade['trade_type']} trade {trade['trade_id']} at {todays_open}, "
                    f"gross={gross:.5f}, spread_cost={spread_cost:.5f}, net={profit:.5f}"
                )

    # Adds exit prices to closed trades and calculates profit or loss
    def add_exit_price(self, store, series_index, new_row_list):
        series = store["ohlcv"][series_index]
        ydays_close = series["Close"].iloc[-1]
        todays_open = new_row_list[series_index]["Open"]
        slippage = abs(ydays_close - todays_open) * 0.2

        trade_records = store["trade_records"][series_index]
        for trade_record in trade_records:
            position_size = trade_record["position_size"]
            if trade_record["closed"] and trade_record["exit_price"] is None and not trade_record["cancelled"]:
                trade_record["exit_price"] = todays_open
                if trade_record["limit_order"]:
                    profit = (todays_open - trade_record["entry_price"]) * position_size if trade_record["trade_type"] == "buy" \
                             else (trade_record["entry_price"] - todays_open) * position_size
                else:
                    profit = ((todays_open - trade_record["entry_price"]) * position_size - slippage * position_size) if trade_record["trade_type"] == "buy" \
                             else ((trade_record["entry_price"] - todays_open) * position_size - slippage * position_size)
                trade_record["profit"] = round(profit, 4)
                store = self.update_trade_history(store, round(profit, 4), series_index)

        store["trade_records"][series_index] = trade_records
        return store

    # Update market-order entry prices at next open and set TP/SL
    def update_entry_prices(self, store, new_row_list, series, series_index, position_size, prompts_on=False):
        trade_records = store["trade_records"][series_index]
        if len(trade_records) > 0:
            todays_open = new_row_list[series_index]["Open"]
            for i, trade_record in enumerate(trade_records):
                if trade_record["entry_price"] is None:
                    trade_record["entry_price"] = todays_open
                    trade_type = trade_record["trade_type"]
                    trade_record["take_profit"] = calculate_take_profit(trade_type, todays_open)
                    trade_record["stop_loss"] = calculate_stop_loss(trade_type, todays_open)
                    trade_records[i] = trade_record
                    if prompts_on:
                        print(f"Series {series_index}. A {trade_type} market order has been placed at {todays_open} "
                              f"for {position_size} unit(s).")
            store["trade_records"][series_index] = trade_records
        return store

    # Increment holding period by 1 for all open trades
    def increment_holding_periods(self, store, series_index):
        trade_records = store["trade_records"][series_index]
        for i, trade_record in enumerate(trade_records):
            if not trade_record["closed"]:
                trade_record["holding_period"] += 1
            trade_records[i] = trade_record
        store["trade_records"][series_index] = trade_records
        return store

    # Check if holding period has expired and close position if needed
    def check_close_positions(self, store, series_index, holding_period, position_size):
        position = False
        trade_type = ""
        trade_records = store["trade_records"][series_index]

        for trade_record in trade_records:
            if not trade_record["closed"]:
                if trade_record["holding_period"] >= holding_period:
                    position_size = trade_record["position_size"]
                    trade_type = trade_record["trade_type"]
                    store = self.close_trade_record(store, series_index, trade_record)
                    position = True

        return {"store": store, "position": position, "size": position_size, "trade_type": trade_type}

    # Update trade history, record Kelly, and mirror p/r/k to store
    def update_trade_history(self, store, profit, series_index, cap=0.5, scale=1.0):
        if series_index not in self.kelly_sizers:
            self.kelly_sizers[series_index] = initialise_kelly(kelly_cap=cap, kelly_scale=scale, use_ema=False)
        kelly = self.kelly_sizers[series_index]

        th = store["trade_histories"][series_index]
        if profit > 0:
            th["wins"].append(profit)
        elif profit < 0:
            th["losses"].append(profit)
        store["trade_histories"][series_index] = th

        kelly.record_trade(profit)
        p = kelly.get_win_probability()
        r = kelly.get_win_loss_ratio()
        k = kelly.calculate_kelly()

        for key in ("win_probability", "win_loss_ratio", "kelly_fraction"):
            store.setdefault(key, [])
            while len(store[key]) <= series_index:
                store[key].append(0.0)

        store["win_probability"][series_index] = p
        store["win_loss_ratio"][series_index] = r
        store["kelly_fraction"][series_index] = k
        return store

    # Execute or cancel pending limit orders based on today's high/low
    def check_if_limit_price_hit(self, store, new_row_list, series, series_index, prompts_on=False):
        latest_date = store["ohlcv"][series_index].index[-1]
        trade_records = store["trade_records"][series_index]

        if len(trade_records) > 0:
            for i, trade_record in enumerate(trade_records):
                entry_price = trade_record["entry_price"]
                trade_direction = trade_record["trade_type"]
                if trade_record["entry_date"] is None:
                    todays_high = new_row_list[series_index]["High"]
                    todays_low = new_row_list[series_index]["Low"]

                    if trade_direction == "buy" and todays_low < entry_price:
                        if prompts_on:
                            print(f"Series {series_index} buy limit executed at {entry_price} on {latest_date}; "
                                  f"low {todays_low} breached the limit.")
                        trade_record["entry_date"] = latest_date

                    elif trade_direction == "sell" and todays_high > entry_price:
                        if prompts_on:
                            print(f"Series {series_index} sell limit executed at {entry_price} on {latest_date}; "
                                  f"high {todays_high} breached the limit.")
                        trade_record["entry_date"] = latest_date

                    else:
                        if prompts_on:
                            print(f"Series {series_index} {trade_direction} limit order removed; "
                                  f"price did not reach limit. Marking cancelled/closed.")
                        trade_record["entry_date"] = latest_date
                        trade_record["cancelled"] = True
                        trade_record["closed"] = True

                    trade_records[i] = trade_record

        store["trade_records"][series_index] = trade_records
        return store

    # Close all open trades for a series and return total position adjustment
    def sell_all_open_positions(self, store, series_index, exit_price):
        adjusted_positions = 0
        trade_records = store["trade_records"][series_index]

        if len(trade_records) > 0:
            for trade_record in trade_records:
                trade_type = trade_record["trade_type"]
                closed = trade_record["closed"]
                position_size = trade_record["position_size"]
                if not closed:
                    if trade_type == "buy":
                        adjusted_positions -= position_size
                        store = self.close_trade_record(store, series_index, trade_record)
                    else:
                        adjusted_positions += position_size
                        store = self.close_trade_record(store, series_index, trade_record)

        return {"adjusted_positions": adjusted_positions, "store": store}

    # Writes out a trade record to a file, for storage
    # Writes all trade records to a timestamped CSV file
    def write_to_file(self, directory=".", prefix="trade_records"):
        if self.df.empty:
            print("No trade records to write.")
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{prefix}_{timestamp}.csv"
        filepath = os.path.join(directory, filename)

        try:
            self.df.to_csv(filepath, index=False)
            print(f"Trade records written to {filepath}")
        except Exception as e:
            print(f"Error writing trade records: {e}")

    # Check take-profits at today's open; close trades if hit, and return position delta
    def check_take_profits(self, store, todays_open, series_index, prompts_on=False):
        position_size = 0.0
        trade_records = store["trade_records"][series_index]
        latest_date = store["ohlcv"][series_index].index[-1]

        # Pre-bind lookups for minor performance gain
        close_trade = self.close_trade_record
        if prompts_on:
            log = print
        else:
            log = lambda *a, **k: None  # no-op if not verbose

        for trade_record in trade_records:
            if trade_record["closed"]:
                continue

            order_type = trade_record["trade_type"]
            tp = trade_record["take_profit"]
            sz = trade_record["position_size"]

            # Check if take-profit hit for long
            if order_type == "buy" and todays_open >= tp:
                position_size -= sz  # sell to close long
                log(f"Series {series_index}: take profit hit at {todays_open}, selling {sz} to close long")
                store = close_trade(store, series_index, trade_record)

            # Check if take-profit hit for short
            elif order_type == "sell" and todays_open <= tp:
                position_size += sz  # buy to close short
                log(f"Series {series_index}: take profit hit at {todays_open}, buying {sz} to close short")
                store = close_trade(store, series_index, trade_record)

        return {"position_size": [position_size], "store": store}

    def remove_timezone(dt):
        return dt.replace(tzinfo=None)