import sys, os, shutil
import pandas as pd
import trading.utils.constants as constants
from trading.utils.config import load_config
from trading.utils.paths import create_run_dir
from trading.strategies.strategy_loader import get_strategy, get_params
from trading.utils.general_utils import load_mid_ohlcv
from trading.utils.logger import start_log, info, warning, error
from trading.backtesting.metrics_report import generate_report
from trading.backtesting.trade_dashboard import build_dashboard
#--------------------------------------------------------------------------------
# Capture command-line arguments
# Argument 0 is the script name
# Argument 1 is --config
# Argument 2 is the config FILENAME only, relative to the configs/ folder
# (load_config() joins it onto CONFIGS_DIR itself — don't include "configs/").
# e.g. backtest_smoke.yaml, NOT configs/backtest_smoke.yaml
# Run with: python scripts/run_backtest.py --config backtest_smoke.yaml
#--------------------------------------------------------------------------------

# Pick the provided path if present, otherwise use default
config_path = sys.argv[2] if len(sys.argv) > 2 and sys.argv[1] == "--config" else constants.CONFIG_DEFAULT
config = load_config(config_path)

# Calculates slippage. Current implementation takes the overnight gap multiplied by a slippage multiplier - This can be optimsied further
def calc_slippage(prev_close, curr_open, slippage_multiplier):
    overnight_gap = abs(prev_close - curr_open)
    return slippage_multiplier * overnight_gap

# Cost of one fill, in the same units as PnL (price x units).
# costs = the "costs" section of the config (params["costs"]):
#   model: "intraday"      -> half the spread + commission on every fill, plus slippage on market and stop fills
#   model: "bid_ask"       -> buys fill at the ask and sells at the bid (real OANDA prices, so the spread is in the
#                             fill price), plus commission on every fill and slippage on market and stop fills
#   model: "overnight_gap" -> the old model: slippage = slippage_multiplier x overnight gap, on market orders only
# If the config has no "costs" section, the old model is used, so older strategies behave exactly as before.
def is_index(pair):
    # index CFDs (SPX500_USD, DE30_EUR...): the first part is not a 3-letter currency
    return len(pair.split("_")[0]) != 3

def pip_size(pair):
    # one "pip" in the config's spread/slippage: 1 point for indices, 0.01 for JPY pairs, 0.0001 otherwise
    if is_index(pair):
        return 1.0
    return 0.01 if "JPY" in pair else 0.0001

def fill_cost(units, price, pair, costs, prices, slippage_multiplier, slippage_on=True):
    if not units:
        return 0.0
    if not costs or costs.get("model", "overnight_gap") == "overnight_gap":
        if not slippage_on:
            return 0.0
        return abs(units) * calc_slippage(prices['prev_close'], prices['curr_open'], slippage_multiplier)
    pip = pip_size(pair)
    if costs["model"] == "bid_ask":
        spread_pips = 0.0          # already paid by filling at the ask / bid
    else:
        spread_pips = costs["spread_pips"].get(pair, costs["spread_pips"].get("default", 0.0))
    per_unit = spread_pips / 2 * pip + costs["commission_pct"] / 100 * price   # pay half the spread on each side
    if slippage_on:
        per_unit += costs["slippage_pips"] * pip
    return abs(units) * per_unit

# --- FX margin account (used when the config sets margin_rate) ---
# P&L comes out in the pair's quote currency (yen for USD_JPY); the account is in USD.
def to_usd(amount, pair, price):
    if is_index(pair):               # index CFDs: P&L stays in the index's own currency (run one index per account)
        return amount
    if pair.endswith("_USD"):        # EUR_USD, GBP_USD...: quote currency is already USD
        return amount
    if pair.startswith("USD_"):      # USD_JPY, USD_CAD...: divide by the price to get USD
        return amount / price
    # Cross pairs (NZD_JPY, CAD_JPY...): APPROXIMATE. Divides by the pair's own price, so the result is in the
    # base currency (NZD, CAD...), treated as if it were USD. Pip results (trades.csv "profit") are exact;
    # the USD balance is only roughly right. A proper fix needs the USD_JPY price loaded alongside.
    return amount / price

# USD value of a position, used for the margin check
def notional_usd(units, pair, price):
    if is_index(pair):
        return abs(units) * price    # in the index's own currency
    if pair.startswith("USD_"):
        return abs(units)            # 1 unit of USD_JPY = 1 USD
    if pair.endswith("_USD"):
        return abs(units) * price    # 1 unit of EUR_USD = price USD
    return abs(units)                # cross pairs: APPROXIMATE, 1 unit of NZD_JPY treated as 1 USD (see to_usd)

# --- Overnight financing (swap), used when the config has a "financing" section (margin mode only) ---
# Holding a position overnight earns the interest gap between the two currencies minus the broker's markup:
# long EUR_USD earns EUR rate - USD rate - markup, short EUR_USD earns USD rate - EUR rate - markup (% a year).
# Rates: FRED 3-month interbank rates in data/rates/<CCY>.csv (monthly). The previous month's value is used,
# so the backtest never uses a rate before it was published.
def load_rates(currencies):
    rates = {}
    for ccy in currencies:
        if len(ccy) != 3:            # an index (SPX500...) earns no interest; holding it long costs the currency's rate
            continue
        df = pd.read_csv(os.path.join(constants.DATA_DIR, "rates", f"{ccy}.csv"), parse_dates=["observation_date"])
        rates[ccy] = df.set_index("observation_date").iloc[:, 0].astype(float).sort_index()
    return rates

def rate_on(rates, ccy, time):
    month_start = pd.Timestamp(time.year, time.month, 1)
    return rates[ccy][rates[ccy].index < month_start].iloc[-1]

def financing_usd(units, pair, price, days, time, rates, markup_pct):
    if units == 0 or days <= 0:
        return 0.0
    base, quote = pair.split("_")
    base_rate = rate_on(rates, base, time) if base in rates else 0.0  # indices: no interest (dividends ignored)
    gap = base_rate - rate_on(rates, quote, time)                      # % a year earned by a long position
    yearly = units * price * gap / 100 - abs(units) * price * markup_pct / 100   # in the quote currency
    return to_usd(yearly * days / 365, pair, price)

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
    if 'AskOpen' in curr_row:   # bid/ask data loaded (bid_ask cost model): buys use the ask, sells the bid
        for side in ('Bid', 'Ask'):
            for p in ('Open', 'High', 'Low'):
                prices[f'curr_{side.lower()}_{p.lower()}'] = curr_row[f'{side}{p}']
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
             slippage_multiplier,
             stop_order1=0, stop_price1=0,
             stop_order2=0, stop_price2=0,
             pair="", costs=None):
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
        info(f"Trade type is MARKET ORDER with value: {market_order}")
        fill_price = prices['curr_open']
        if 'curr_ask_open' in prices:   # bid_ask model: buy at the ask, sell at the bid
            fill_price = prices['curr_ask_open'] if market_order > 0 else prices['curr_bid_open']
        cost = fill_cost(market_order, fill_price, pair, costs, prices, slippage_multiplier)
        pnl += market_order * (prices['next_open'] - fill_price) - cost
        # Cash impact: executed “at current open” plus costs (R model)
        money_spent += (market_order * fill_price) + cost
        new_pos += market_order

    # --- Limit orders (each can fill once, valid for next day only) ---
    # Limit fills pay spread + commission but no slippage
    for fill in (check_limit_order(prices, limit_order1, limit_price1),
                 check_limit_order(prices, limit_order2, limit_price2)):
        cost = fill_cost(fill['new_pos'], fill['price'], pair, costs, prices, slippage_multiplier, slippage_on=False)
        pnl += fill['pnl'] - cost
        money_spent += fill['money_spent'] + cost
        new_pos += fill['new_pos']

    # --- Stop orders (each can fill once, valid for this bar only) ---
    # If both trigger in the same bar, both fill (we can't tell which came first, so assume the worst).
    for fill in (check_stop_order(prices, stop_order1, stop_price1),
                 check_stop_order(prices, stop_order2, stop_price2)):
        cost = fill_cost(fill['new_pos'], fill['price'], pair, costs, prices, slippage_multiplier)
        pnl += fill['pnl'] - cost
        money_spent += fill['money_spent'] + cost
        new_pos += fill['new_pos']

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

    costs = params.get("costs")  # None -> old overnight-gap slippage model
    margin_rate = params.get("margin_rate")  # None -> old cash model; e.g. 0.0333 = 1:30 leverage (FX margin account in USD)
    financing = params.get("financing")      # None -> no swap; e.g. {markup_pct: 1.5}
    if financing is not None:
        rates = load_rates({c for pair in params["pairs"] for c in pair.split("_")})
    time_index = data_list[0].index

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
        if margin_rate is not None:
            portfolio_net_worth = balance   # margin account: open P&L is already in the balance
        else:
            portfolio_net_worth = balance + sum(current_pos[j] * curr_rows[j]['Open'] for j in range(num_series))
        # NOTE: named state_info (not "info") so it doesn't shadow the
        # trading.utils.logger.info() function used for logging below.
        state_info = {"balance": balance, "netWorth": portfolio_net_worth}

        # 3) Get orders — strategy sees ONLY current data (no lookahead possible)
        orders = strategy_function(store, new_row_list, current_pos, state_info, params)
        market_orders = orders["marketOrders"]  # list len=num_series
        limit_orders_1 = orders.get("limitOrders1", [0] * num_series)
        limit_prices_1 = orders.get("limitPrices1", [0] * num_series)
        limit_orders_2 = orders.get("limitOrders2", [0] * num_series)
        limit_prices_2 = orders.get("limitPrices2", [0] * num_series)
        stop_orders_1 = orders.get("stopOrders1", [0] * num_series)
        stop_prices_1 = orders.get("stopPrices1", [0] * num_series)
        stop_orders_2 = orders.get("stopOrders2", [0] * num_series)
        stop_prices_2 = orders.get("stopPrices2", [0] * num_series)
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
                slippage_multiplier=slippage_multiplier,
                stop_order1=stop_orders_1[j],
                stop_price1=stop_prices_1[j],
                stop_order2=stop_orders_2[j],
                stop_price2=stop_prices_2[j],
                pair=params['pairs'][j],
                costs=costs,
            )
            trade_results.append(res)
            money_spent_total += res['money_spent']
            new_positions[j] = res['new_pos']
            position_values[j] = res['current_value']
            base_pnls[j] = res['base_pnl']
            pnls[j] = res['pnl']


        if margin_rate is not None:
            # FX margin account: P&L is converted to USD and added to the balance every bar (marked to market),
            # no cash is "spent" on a position. New trades are cancelled if the margin needed is more than the equity.
            pnls_usd = [to_usd(pnls[j], params['pairs'][j], prices_list[j]['next_open']) for j in range(num_series)]
            margin_needed = sum(notional_usd(new_positions[j], params['pairs'][j], prices_list[j]['next_open'])
                                for j in range(num_series)) * margin_rate
            if margin_needed > balance + sum(pnls_usd) and new_positions != current_pos:
                warning(f"Not enough margin on period {i + 1}: trade cancelled", __file__)
                new_positions = current_pos[:]
                pnls_usd = [to_usd(base_pnls[j], params['pairs'][j], prices_list[j]['next_open']) for j in range(num_series)]
            if financing is not None:   # swap on the positions held from this open to the next open
                days = (time_index[i + 1] - time_index[i]).total_seconds() / 86400
                for j in range(num_series):
                    pnls_usd[j] += financing_usd(new_positions[j], params['pairs'][j], prices_list[j]['next_open'],
                                                 days, time_index[i], rates, financing["markup_pct"])
            balance += sum(pnls_usd)
            current_pos = new_positions[:]
            if any(abs(p) > 0 for p in current_pos):
                pos_days += 1
            for j in range(num_series):
                pnl_lists[j].append(pnls_usd[j])
            net_worth = balance
            portfolio_net_worth_list.append(net_worth)
            if net_worth <= 0:
                warning(f"Bankrupt on period {i + 1}", __file__)
                break
            continue

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
            warning(f"Bankrupt on period {i + 1}", __file__)
            # Liquidate as if final day using today's prev/curr (i-1, i)
            exit_pnls = []
            exit_values = []
            for j in range(num_series):
                prices_liq = get_prices(prev_rows[j], curr_rows[j], None)
                pnl_slip, nw = final_exit(prices_liq, current_pos[j], slippage_multiplier, params['pairs'][j], costs)
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
        pnl_slip, nw = final_exit(prices_last, current_pos[j], slippage_multiplier, params['pairs'][j], costs)
        final_exit_pnls.append(pnl_slip)
        final_exit_values.append(nw)

    if margin_rate is not None:   # margin account: only the closing cost, converted to USD (P&L is already in the balance)
        balance += sum(to_usd(final_exit_pnls[j], params['pairs'][j], data_list[j].iloc[-1]['Open']) for j in range(num_series))
        final_exit_values = [0.0] * num_series
    else:
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
    # --- Collect trade records ---
    # Writing these to disk (and generating the metrics report) is the
    # caller's job — see run_backtest() below, which owns the run folder.
    all_trades = []
    for symbol, trade_rec_obj in store.get("trade_records", {}).items():  # older strategies
        all_trades.append(trade_rec_obj.trade_records.copy())
    for symbol, trades in store.get("trade_list", {}).items():  # London Breakout
        all_trades.append(pd.DataFrame(trades))

    trades_df = pd.concat(all_trades, ignore_index=True) if all_trades else pd.DataFrame()
    if not trades_df.empty:
        info(f"Last trades:\n{trades_df.tail().to_string()}")
    else:
        warning("No trade records generated.", __file__)

    return {
        "pnlList": pnl_dfs,
        "netWorthList": portfolio_net_worth_list,
        "k": k,
        "trades_df": trades_df,
    }

def close_out(prices, pos, slippage_multiplier, pair="", costs=None):
    cost = fill_cost(pos, prices['curr_open'], pair, costs, prices, slippage_multiplier)  # cost to liquidate via market
    if 'curr_ask_open' in prices:   # bid_ask model: closing also pays half the spread (P&L is marked at the mid)
        cost += abs(pos) * (prices['curr_ask_open'] - prices['curr_bid_open']) / 2
    return -cost

def final_exit(prices, pos, slippage_multiplier, pair="", costs=None):
    pnl_slip = close_out(prices, pos, slippage_multiplier, pair, costs)
    net_worth = prices['curr_open'] * pos + pnl_slip
    return pnl_slip, net_worth

def check_limit_order(prices, limit_order, limit_price):
    eps = 0.0001  # small tolerance for float comparison

    pnl = 0.0
    new_pos = 0.0
    money_spent = 0.0
    execution_price = None

    # --- Check if limit order can execute ---
    # bid_ask model: a buy limit fills when the ask trades below it, a sell limit when the bid trades above it
    low = prices.get('curr_ask_low', prices['curr_low'])
    high = prices.get('curr_bid_high', prices['curr_high'])
    buy_condition = limit_order > 0 and low < (limit_price - eps)
    sell_condition = limit_order < 0 and high > (limit_price + eps)

    if buy_condition or sell_condition:
        # --- Determine execution price ---
        if limit_order > 0:
            # Buy limit: execute at min(limit_price, current high)
            execution_price = min(limit_price, prices.get('curr_ask_high', prices['curr_high']))
        else:
            # Sell limit: execute at max(limit_price, current low)
            execution_price = max(limit_price, prices.get('curr_bid_low', prices['curr_low']))

        # --- Calculate PnL and cost ---
        pnl = limit_order * (prices['next_open'] - execution_price)
        money_spent = execution_price * limit_order
        new_pos = limit_order

    return {'pnl': pnl, 'money_spent': money_spent, 'new_pos': new_pos, 'price': execution_price}

# Stop order: buy when price rises TO stop_price, sell when it falls to it.
# Used for breakout entries (buy above the range) and protective stop losses that fill inside the bar.
# Valid for the current bar only. If the bar opens past the stop (a gap), it fills at the open, which is worse.
def check_stop_order(prices, stop_order, stop_price):
    pnl = 0.0
    new_pos = 0.0
    money_spent = 0.0
    execution_price = None

    # bid_ask model: a buy stop triggers and fills on the ask, a sell stop on the bid (like OANDA)
    if stop_order > 0 and prices.get('curr_ask_high', prices['curr_high']) >= stop_price:
        execution_price = max(prices.get('curr_ask_open', prices['curr_open']), stop_price)
    elif stop_order < 0 and prices.get('curr_bid_low', prices['curr_low']) <= stop_price:
        execution_price = min(prices.get('curr_bid_open', prices['curr_open']), stop_price)

    if execution_price is not None:
        pnl = stop_order * (prices['next_open'] - execution_price)
        money_spent = execution_price * stop_order
        new_pos = stop_order

    return {'pnl': pnl, 'money_spent': money_spent, 'new_pos': new_pos, 'price': execution_price}

def check_lengths(num_series, orders):
    for k in ("marketOrders","limitOrders1","limitPrices1","limitOrders2","limitPrices2",
              "stopOrders1","stopPrices1","stopOrders2","stopPrices2"):
        if k in orders and len(orders[k]) != num_series:
            raise ValueError(f"len({k})={len(orders[k])} != num_series={num_series}")

def _load_series_for_pair(pair, params):
    if params["security_type"] != "forex" or params["provider"] != "OANDA":
        raise NotImplementedError(
            f"No loader for provider={params['provider']}, "
            f"security_type={params['security_type']}"
        )

    timeframe = params["timeframe"]
    start_date = params["start_date"]
    end_date = params["end_date"]
    year = params.get("year")

    if year is None:
        frames = []
        for y in range(int(start_date), int(end_date) + 1):
            merged_file = os.path.join(constants.OANDA_FOREX_DATA_DIR, pair, str(y), timeframe,
                                       "merged", f"{pair}_{y}.csv")
            frames.append(load_mid_ohlcv(merged_file, keep_bid_ask=(params.get("costs") or {}).get("model") == "bid_ask"))
        series = pd.concat(frames).sort_index()
        return series[~series.index.duplicated()]

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

def run_backtest(strategy, params, config_path=None):
    # Every run gets its own folder — and its own run.log — from the very
    # start, so a crash during data loading / simulation still gets captured
    # inside that run's folder rather than only going to the console.
    run_dir = create_run_dir(params["strategy_name"])
    start_log(log_dir=run_dir, filename="run.log")
    info(f"Starting backtest run. strategy={params.get('strategy_name')} run_dir={run_dir}")

    # Snapshot the config alongside everything else this run produces.
    if config_path:
        # Same resolution load_config() uses internally: os.path.join discards
        # CONFIGS_DIR if config_path is already absolute, so this works either way.
        resolved_config_path = os.path.join(constants.CONFIGS_DIR, config_path)
        if os.path.exists(resolved_config_path):
            shutil.copy(resolved_config_path, os.path.join(run_dir, "config.yaml"))
            info(f"Config snapshotted to {os.path.join(run_dir, 'config.yaml')}")
        else:
            warning(f"Config file not found for snapshotting: {resolved_config_path}", __file__)

    try:
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
    except Exception as e:
        error(f"Backtest run failed: {e}", __file__)
        raise

    # 3. INSPECT
    networth_vec = results["netWorthList"]
    k_ratio = results["k"]
    pnl_dfs = results["pnlList"]

    info("=" * 60)
    info("PER-PAIR P&L")
    info("=" * 60)
    for pair, pnl_df in zip(params["pairs"], pnl_dfs):
        final_cum = pnl_df["CumPnL"].iloc[-1]
        n_winning = (pnl_df["DailyPnL"] > 0).sum()
        n_losing = (pnl_df["DailyPnL"] < 0).sum()
        info(f"{pair}: Final CumPnL={final_cum:.2f}, Winning days={n_winning}, Losing days={n_losing}")
        info(f"{pair} last 5 rows:\n{pnl_df.tail().to_string()}")

    info("=" * 60)
    info("PORTFOLIO")
    info("=" * 60)
    info(f"Final Net Worth: {networth_vec[-1]:.2f}")
    info(f"k (days in position %): {k_ratio}")

    # 4. SAVE — everything this run produced lives together in run_dir:
    #    results/<strategy>/<run_id>/{config.yaml, trades.csv, metrics.json, report.html, figures/, run.log}
    # Bar-by-bar P&L per pair (includes costs), used by the charts notebook
    equity = pd.concat({pair: df["CumPnL"] for pair, df in zip(params["pairs"], pnl_dfs)}, axis=1)
    equity.to_csv(os.path.join(run_dir, "equity.csv"))
    info(f"Equity curve saved to {os.path.join(run_dir, 'equity.csv')}")

    trades_df = results.get("trades_df")
    if trades_df is not None and not trades_df.empty:
        trades_path = os.path.join(run_dir, "trades.csv")
        trades_df.to_csv(trades_path, index=False)
        info(f"Trade records saved to {trades_path}")

        generate_report(run_dir)
        build_dashboard(run_dir, data_list, params)   # dashboard.html: stats + interactive charts, opens in the browser
        info(f"Full run output saved to: {run_dir}")
    else:
        warning("No trade records generated — skipping report generation.", __file__)

    return results

if __name__ == "__main__":
    strategy = get_strategy(config["strategy"])
    params = get_params(config)

    run_backtest(strategy, params, config_path=config_path)
