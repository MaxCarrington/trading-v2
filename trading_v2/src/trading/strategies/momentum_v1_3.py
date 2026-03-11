import src.trading.utils.constants as constants

from src.trading.data.data_analysis.mean_rev_analysis import get_series_mean_rev_stats, print_mean_rev_analysis
from src.trading.data.data_analysis.momentum_analysis import get_momentum_statistics, print_momentum_analysis
from src.trading.data.data_analysis.volatility_analysis import get_volatility_statistics, print_volatility_analysis
from src.trading.data.data_analysis.analysis import determine_momentum_or_mean_rev, is_momentum
from src.trading.utils.logger import start_log, info, warning, error

def trade_periods_of_momentum(series,
                              asset,
                              timeframe,
                              start_date,
                              end_date,
                              p_val_len_thresh,
                              volatility_lookback,
                              price_to_use,
                              min_periods=100,
                              print_output=False):
    i = min_periods  # Start index after enough data exists to form the first rolling window
    momentum_trades = []  # Stores (start_idx, end_idx) for detected momentum trades
    prev_regime = None
    trade_open = False
    trade_start = None
    profits = []
    trade_durations = []
    # Outer loop: scan forward through the series to detect regime starts
    while i < len(series):
        # Rolling window ending at index i, used to classify current regime
        window = series.iloc[i - min_periods:i]
        # Compute momentum statistics for the current window
        momentum_stats = get_momentum_statistics(window, p_val_len_thresh, asset, timeframe, start_date, end_date,
                                                 price_to_use, print_output=print_output)
        mean_rev_stats = get_series_mean_rev_stats(window, asset, timeframe, start_date, end_date, price_to_use,
                                                   print_output=print_output)
        # Compute volatility statistics for the current window
        volatility_stats = get_volatility_statistics(window, volatility_lookback, asset, timeframe, start_date,
                                                     end_date, price_to_use, print_output=print_output)

        # Classify the current regime based on momentum vs mean-reversion evidence
        current_pattern = determine_momentum_or_mean_rev(momentum_stats, mean_rev_stats, print_output=print_output)

        # --- Detect regime transitions ---
        if prev_regime != current_pattern:

            # Momentum begins → open trade
            if current_pattern == "momentum":
                trade_open = True
                trade_start = i

            # Momentum ends → close trade
            elif prev_regime == "momentum" and trade_open:
                indexes = (trade_start, i - 1)
                profit = generate_profit(series, trade_start, i-1)
                momentum_trades.append({
                    "index": indexes,
                    "profit": profit
                })
                profits.append(profit)
                trade_durations.append(trade_start - (i-1))
                trade_open = False
                trade_start = None

        prev_regime = current_pattern
        i += 1
    if trade_open:
        profit = generate_profit(series, trade_start, len(series) - 1)
        momentum_trades.append({
            "index": (trade_start, len(series) - 1),
            "profit": profit
        })

    print(momentum_trades)
    print(trade_durations)
    print(profits)


def generate_profit (series, start_idx, end_idx):
    start_price = series.iloc[start_idx, series.columns.get_loc("MidClose")]
    end_price = series.iloc[end_idx, series.columns.get_loc("MidClose")]
    profit = end_price - start_price
    return profit
