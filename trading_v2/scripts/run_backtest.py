import sys, os
import pandas as pd
from datetime import datetime
import math
import trading.utils.constants as constants
from trading.utils.config import load_config
from trading.strategies.strategy_loader import get_strategy, get_params
from trading.utils.general_utils import load_mid_ohlcv, load_mid_ohlcv_range
from trading.utils.logger import start_log, info, warning, error
from trading.utils.data_manipulation import get_forex_data, create_asset_dictonary
#--------------------------------------------------------------------------------
# Capture command-line arguments
# Argument 0 is the script name
# Argument 1 is --config
# Argument 2 is the config file path (e.g. configs/backtest_smoke.yaml)
# Run with: python scripts/run_backtest.py --config configs/backtest_smoke.yaml
#--------------------------------------------------------------------------------

# Pick the provided path if present, otherwise use default
config_path = sys.argv[2] if len(sys.argv) > 2 and sys.argv[1] == "--config" else constants.CONFIG_DEFAULT
config = load_config(config_path)

# Set up logging
#start_log(config_path, config)

# Calculates slippage. Current implementation takes the overnight gap multiplied by a slippage multiplier - This can be optimsied further
def calc_slippage(prev_close, curr_open, slippage_multiplier):
    overnight_gap = abs(prev_close - curr_open)
    return slippage_multiplier * overnight_gap

# Gets the previous close, open, high, low and current close, open, high, low
def get_prices(prev_row, curr_row, next_row=None):
    prices = {
        # previous
        'prev_close': prev_row['Close'],
        'prev_open':  prev_row['Open'],
        'prev_high':  prev_row['High'],
        'prev_low':   prev_row['Low'],
        # current
        'curr_close': curr_row['Close'],
        'curr_open':  curr_row['Open'],
        'curr_high':  curr_row['High'],
        'curr_low':   curr_row['Low'],
    }
    if next_row is not None:
        prices['next_open'] = next_row['Open']
        prices['next_high'] = next_row['High']  # optional but handy
        prices['next_low']  = next_row['Low']   # optional but handy
    return prices

# Calculates net PnL by multiplying position size with price change between opens,
# applying slippage costs only when executing market orders.
def find_pnl(prices, old_pos, market_order,
             limit_order1, limit_price1,
             limit_order2, limit_price2,
             slippage_multiplier):
    """
    prices: dict from get_prices(prev, curr, next)
    Returns dict: pnl, base_pnl, money_spent, new_pos, current_value, old_value
    """
    # base PnL from holding old position from curr_open -> next_open
    base_pnl = old_pos * (prices['next_open'] - prices['curr_open'])
    pnl = base_pnl
    new_pos = old_pos
    money_spent = 0.0

    # Value before trades (used if trades later get cancelled due to overspend)
    old_value = prices['next_open'] * old_pos

    # --- Market order execution at next open with slippage cost at current open ---
    if market_order != 0:
        slippage = calc_slippage(prices['prev_close'], prices['curr_open'], slippage_multiplier)
        pnl += market_order * (prices['next_open'] - prices['curr_open']) - abs(market_order) * slippage
        # Cash impact: executed “at current open” with slippage (R model)
        money_spent += (market_order * prices['curr_open']) + (abs(market_order) * slippage)
        new_pos += market_order

    # --- Limit orders (each can fill once, valid for next day only) ---
    l1 = check_limit_order(prices, limit_order1, limit_price1)
    l2 = check_limit_order(prices, limit_order2, limit_price2)

    pnl += l1['pnl'] + l2['pnl']
    money_spent += l1['money_spent'] + l2['money_spent']
    new_pos += l1['new_pos'] + l2['new_pos']

    current_value = prices['next_open'] * new_pos

    return {
        'pnl': pnl,
        'base_pnl': base_pnl,
        'money_spent': money_spent,
        'new_pos': new_pos,
        'current_value': current_value,
        'old_value': old_value
    }

# Backtester that simulates a live environment for multiple series
def backtest_live(data_list, strategy_function, params, slippage_multiplier, strategy_name):
    num_periods = len(data_list[0])  # Assumes all series have same number of rows
    num_series = len(params['pairs'])
    balance = params['starting_capital']
    current_pos = [0] * num_series  # One position per series
    # For each series, store a list of daily pnl values.
    pnl_lists = [[] for _ in range(num_series)]
    portfolio_net_worth_list = []

    # Initialize persistent store (None initially)
    store = None
    pos_days = 0
    # Loop over each time step (simulate receiving one new row per series)
    for i in range(1, num_periods - 1):

        # 1) Build ONLY current-row inputs for the strategy
        curr_rows = [df.iloc[i] for df in data_list]
        prev_rows = [df.iloc[i - 1] for df in data_list]
        new_row_list = [
            {**row.to_dict(), "Time": row.name} for row in prev_rows
        ]

        # 2) Compute info (no future fields)
        portfolio_net_worth = balance + sum(current_pos[j] * curr_rows[j]['Open'] for j in range(num_series))
        info = {"balance": balance, "netWorth": portfolio_net_worth}

        # 3) Get orders — strategy sees ONLY current data (no lookahead possible)
        orders = strategy_function(store, new_row_list, current_pos, info, params)
        market_orders = orders["marketOrders"]  # list len=num_series
        limit_orders_1 = orders.get("limitOrders1", [0] * num_series)
        limit_prices_1 = orders.get("limitPrices1", [0] * num_series)
        limit_orders_2 = orders.get("limitOrders2", [0] * num_series)
        limit_prices_2 = orders.get("limitPrices2", [0] * num_series)
        store = orders["store"]
        check_lengths(num_series, orders)
        # 4) Now it’s safe to look at the next bar to settle PnL (simulate next open)
        prices_list = []
        for j in range(num_series):
            next_row = data_list[j].iloc[i + 1]
            price_data = get_prices(prev_rows[j], curr_rows[j], next_row)
            prices_list.append(price_data)

        # Execute all series and aggregate
        trade_results = []
        money_spent_total = 0.0
        new_positions = [0] * num_series
        position_values = [0.0] * num_series
        base_pnls = [0.0] * num_series
        pnls = [0.0] * num_series

        for j in range(num_series):
            res = find_pnl(
                prices=prices_list[j],
                old_pos=current_pos[j],
                market_order=market_orders[j],
                limit_order1=limit_orders_1[j],
                limit_price1=limit_prices_1[j],
                limit_order2=limit_orders_2[j],
                limit_price2=limit_prices_2[j],
                slippage_multiplier=slippage_multiplier
            )
            trade_results.append(res)
            money_spent_total += res['money_spent']
            new_positions[j] = res['new_pos']
            position_values[j] = res['current_value']
            base_pnls[j] = res['base_pnl']
            pnls[j] = res['pnl']


        # Overspend check: cancel trades if insufficient cash
        if money_spent_total > balance:
            # revert to base pnl and old positions
            pnls = base_pnls[:]
            new_positions = current_pos[:]
            money_spent_total = 0.0
            position_values = [tr['old_value'] for tr in trade_results]

        # Realize PnL and update cash/positions
        balance -= money_spent_total
        current_pos = new_positions[:]

        if any(abs(p) > 0 for p in current_pos):
            pos_days += 1

        # Store per-series PnL (open->next open)
        for j in range(num_series):
            pnl_lists[j].append(pnls[j])

        new_net_worth = sum(position_values)
        net_worth = new_net_worth + balance
        portfolio_net_worth_list.append(net_worth)

        if net_worth <= 0:
            print(f"Bankrupt on period {i + 1}")
            # Liquidate as if final day using today's prev/curr (i-1, i)
            exit_pnls = []
            exit_values = []
            for j in range(num_series):
                prices_liq = get_prices(prev_rows[j], curr_rows[j], None)
                pnl_slip, nw = final_exit(prices_liq, current_pos[j], slippage_multiplier)
                exit_pnls.append(pnl_slip)
                exit_values.append(nw)

            balance += sum(exit_pnls)
            net_worth = sum(exit_values) + balance
            portfolio_net_worth_list.append(net_worth)
            # Optionally record per-series PnL for the bankruptcy day:
            for j in range(num_series):
                pnl_lists[j].append(exit_pnls[j])
            break

    # Final day: close out with slippage (mirror R)
    final_exit_pnls = []
    final_exit_values = []
    for j in range(num_series):
        # Treat penultimate as prev, last as curr
        prices_last = get_prices(data_list[j].iloc[-2], data_list[j].iloc[-1], None)
        pnl_slip, nw = final_exit(prices_last, current_pos[j], slippage_multiplier)
        final_exit_pnls.append(pnl_slip)
        final_exit_values.append(nw)

    balance += sum(final_exit_pnls)
    final_net_worth = sum(final_exit_values) + balance
    portfolio_net_worth_list.append(final_net_worth)

    # build DataFrames like the R engine expects
    pnl_dfs = []
    idx = data_list[0].index  # assumes aligned indices
    for j in range(num_series):
        s = pd.Series(pnl_lists[j], index=idx[1:len(pnl_lists[j]) + 1])  # align to the days you appended
        df = pd.DataFrame({"DailyPnL": s})
        df["CumPnL"] = df["DailyPnL"].cumsum()
        pnl_dfs.append(df)

    k = round(100 * pos_days / max(1, (num_periods - 2)))
    # --- Collect and export trade records ---
    all_trades = []
    for symbol, trade_rec_obj in store["trade_records"].items():
        df = trade_rec_obj.trade_records.copy()
        all_trades.append(df)

    if all_trades:
        trades_df = pd.concat(all_trades, ignore_index=True)
        print(trades_df.tail())  # print last few trades neatly

        # Optional: export to CSV
        trades_csv_path = os.path.join(
            constants.PROJECT_ROOT,
            "results",
            "backtest_results",
            strategy_name,
            datetime.now().strftime('%Y%m%d'),
            f"trade_records_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        )

        os.makedirs(os.path.dirname(trades_csv_path), exist_ok=True)
        trades_df.to_csv(trades_csv_path, index=False)
        print(f"Trade records exported to {trades_csv_path}")
    else:
        print("No trade records generated.")

    return {"pnlList": pnl_dfs, "netWorthList": portfolio_net_worth_list, "k": k}

def close_out(prices, pos, slippage_multiplier):
    slippage = calc_slippage(prices['prev_close'], prices['curr_open'], slippage_multiplier)
    return -abs(pos) * slippage  # cost to liquidate via market

def final_exit(prices, pos, slippage_multiplier):
    pnl_slip = close_out(prices, pos, slippage_multiplier)
    net_worth = prices['curr_open'] * pos + pnl_slip
    return pnl_slip, net_worth

def check_limit_order(prices, limit_order, limit_price):
    eps = 0.0001  # small tolerance for float comparison

    pnl = 0.0
    new_pos = 0.0
    money_spent = 0.0

    # --- Check if limit order can execute ---
    buy_condition = limit_order > 0 and prices['curr_low'] < (limit_price - eps)
    sell_condition = limit_order < 0 and prices['curr_high'] > (limit_price + eps)

    if buy_condition or sell_condition:
        # --- Determine execution price ---
        if limit_order > 0:
            # Buy limit: execute at min(limit_price, current high)
            execution_price = min(limit_price, prices['curr_high'])
        else:
            # Sell limit: execute at max(limit_price, current low)
            execution_price = max(limit_price, prices['curr_low'])

        # --- Calculate PnL and cost ---
        pnl = limit_order * (prices['next_open'] - execution_price)
        money_spent = execution_price * limit_order
        new_pos = limit_order

    return {'pnl': pnl, 'money_spent': money_spent, 'new_pos': new_pos}

def check_lengths(num_series, orders):
    for k in ("marketOrders","limitOrders1","limitPrices1","limitOrders2","limitPrices2"):
        if k in orders and len(orders[k]) != num_series:
            raise ValueError(f"len({k})={len(orders[k])} != num_series={num_series}")

def _load_series_for_pair(pair, params):
    year       = params["year"]
    timeframe  = params["timeframe"]
    start_date = params["start_date"]
    end_date   = params["end_date"]

    if params["security_type"] != "forex" or params["provider"] != "OANDA":
        raise NotImplementedError(
            f"No loader for provider={params['provider']}, "
            f"security_type={params['security_type']}"
        )

    # Always load the merged yearly file — it contains every bar fetched for
    # the year. Date-range slicing below uses the configured start/end dates.
    base_dir    = os.path.join(constants.OANDA_FOREX_DATA_DIR, pair, year, timeframe)
    merged_file = os.path.join(base_dir, "merged", f"{pair}_{year}.csv")

    if not os.path.exists(merged_file):
        raise FileNotFoundError(
            f"Merged data file not found for {pair} ({year} {timeframe}):\n"
            f"  {merged_file}\n"
            f"Run scripts/generate_backtest_data.py to fetch this data first."
        )

    series = load_mid_ohlcv(merged_file)

    # Slice to the configured date range. For full-year daily configs,
    # start_date == end_date == year produces a slice that covers the whole year.
    if timeframe in ("D", "H4", "H1", "M30", "M15", "M5", "M1"):
        start_str = f"{year}-{start_date}" if start_date != year else year
        end_str   = f"{year}-{end_date}"   if end_date   != year else year
        return series.loc[start_str:end_str]

    raise ValueError(f"Unknown timeframe: {timeframe}")

def _align_dataframes(dfs):
    """
    Inner-join all DataFrames on their time index so every series has
    the same length and the same timestamps. Drops timestamps not
    present in every series (e.g. one pair has a holiday candle the others don't).
    """
    if len(dfs) <= 1:
        return dfs

    common_index = dfs[0].index
    for df in dfs[1:]:
        common_index = common_index.intersection(df.index)

    aligned = [df.loc[common_index].sort_index() for df in dfs]

    # Sanity check
    n = len(aligned[0])
    for j, df in enumerate(aligned):
        if len(df) != n:
            raise RuntimeError(f"Alignment failed: series {j} has {len(df)} rows, expected {n}")

    return aligned

def run_backtest(strategy, params):
    data_list = []
    for pair in params["pairs"]:
        series = _load_series_for_pair(pair, params)  # <-- your existing branching, extracted
        data_list.append(series)
    data_list = _align_dataframes(data_list)
    # 2. BACKTEST once, on the whole list
    slippage_multiplier = 0.2
    results = backtest_live(
        data_list=data_list,
        strategy_function=strategy,
        params=params,
        slippage_multiplier=slippage_multiplier,
        strategy_name=params["strategy_name"],
    )

    # 3. INSPECT
    networth_vec = results["netWorthList"]
    k_ratio = results["k"]
    pnl_dfs = results["pnlList"]

    print("\n" + "=" * 60)
    print("PER-PAIR P&L")
    print("=" * 60)
    for pair, pnl_df in zip(params["pairs"], pnl_dfs):
        final_cum = pnl_df["CumPnL"].iloc[-1]
        n_winning = (pnl_df["DailyPnL"] > 0).sum()
        n_losing = (pnl_df["DailyPnL"] < 0).sum()
        print(f"\n{pair}:")
        print(f"  Final CumPnL: {final_cum:.2f}")
        print(f"  Winning days: {n_winning}, Losing days: {n_losing}")
        print(f"  Last 5 rows:")
        print(pnl_df.tail().to_string())

    print("\n" + "=" * 60)
    print("PORTFOLIO")
    print("=" * 60)
    print(f"Final Net Worth: {networth_vec[-1]:.2f}")
    print(f"k (days in position %): {k_ratio}")

    #generate_metrics_report_main()

if __name__ == "__main__":
    strategy = get_strategy(config["strategy"])
    params = get_params(config)

    run_backtest(strategy, params)


