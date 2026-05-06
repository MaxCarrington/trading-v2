import trading.utils.constants as constants

from trading.data.data_analysis.mean_rev_analysis import get_series_mean_rev_stats, print_mean_rev_analysis
from trading.data.data_analysis.momentum_analysis import get_momentum_statistics, print_momentum_analysis
from trading.data.data_analysis.volatility_analysis import get_volatility_statistics, print_volatility_analysis
from trading.data.data_analysis.volume_analysis import combined_liquidity_analysis, print_liquidity_analysis
from trading.utils.config import load_config
from trading.utils.logger import start_log, info, warning, error

CONFIGS_DIR = constants.CONFIGS_DIR
# Perform data analysis to generate mean-reversion, momentum, volatility and volume data
def perform_analysis(series, asset, timeframe, start_date, end_date, config_file, is_forex=True, print_output=False):
    # Load in the config files
    info(f"Current file is {__file__}")
    info(f"Performing analysis for {asset} on {timeframe} from {start_date} to {end_date}")
    analysis_params = load_config(config_file)
    info(f"Analysis Parameters: {analysis_params} ")
    liquidity_stats = None
    # Generate strategy data analysis
    info("Generating momentum statistics.....\n \n")
    momentum_stats = get_momentum_statistics(series, analysis_params["p-val_len_thresh"], asset, timeframe, start_date, end_date, print_output=print_output)
    info("Generating mean reversion statistics.....\n \n")
    mean_rev_stats = get_series_mean_rev_stats(series, asset, timeframe, start_date, end_date, print_output=print_output)
    info("Generating volatility statistics......\n \n")
    volatility_stats = get_volatility_statistics(series, analysis_params["volatility_lookback"], asset, timeframe, start_date, end_date, print_output=print_output)

    if not is_forex:
        info("Generating liquidity statistics\n \n")
        liquidity_stats = combined_liquidity_analysis(series, asset, timeframe, start_date, end_date, print_output=print_output)

    strategy = determine_momentum_or_mean_rev(momentum_stats, mean_rev_stats, volatility_stats, liquidity_stats, print_output=print_output)
    return {
        "strategy": strategy,
        "momentum_stats": momentum_stats,
        "mean_rev_stats": mean_rev_stats,
        "volatility_stats": volatility_stats,
        "liquidity_stats": liquidity_stats
    }

# Determines the best strategy to used between normalised (z-score) data analysis results
def determine_momentum_or_mean_rev(momentum_stats=None, mean_rev_stats=None, volatility_stats=None, liquidity_stats=None, print_output=False, minimum_strategy_thrsh=50):
    mr_z_score = mean_rev_stats['normalised_score']
    momentum_z_score = momentum_stats['normalised_score']

    if mr_z_score >= minimum_strategy_thrsh and mr_z_score > momentum_z_score:
        verdict = "✅ Mean-Reversion Selected"
        strategy = "mean_reversion"
    elif momentum_z_score >= minimum_strategy_thrsh and momentum_z_score > mr_z_score:
        verdict = "✅ Momentum Selected"
        strategy = "momentum"
    else:
        verdict = "❌ No Suitable Strategy"
        strategy = "none"

    if print_output:
        info(f"Mean Reversion z-score: {mr_z_score}")
        info(f"Momentum z-score: {momentum_z_score}")
        info(f"🧠 Strategy Verdict: {verdict}")
        print("-" * 50)
        info("-" * 50)

    return strategy

def is_momentum(momentum_stats, volatility_stats, minimum_momentum_thresh=70, high_volatility_thresh = 70, low_volatility_thresh = 30, trade_high_volatility=False, trade_w_volatility=True):
    # Test for momentum, if trading with volatility in highly volatile periods
    has_momentum = momentum_stats["normalised_score"] > minimum_momentum_thresh
    volatility_high = volatility_stats["combined_score"].iloc[-1] >= high_volatility_thresh
    volatility_low = volatility_stats["combined_score"].iloc[-1] <= low_volatility_thresh
    # determines whether momentum trading is permitted based on the flags
    if not has_momentum:
        print(f"Momentum statistics not found, momentum score: {momentum_stats['normalised_score']}")
        return False, momentum_stats["normalised_score"]

    if trade_w_volatility:
        if volatility_high and trade_high_volatility:
            print("Momentum found, trading with high volatility")
            return True, momentum_stats["normalised_score"]
        elif volatility_low and not trade_high_volatility:
            print("Momentum found, trading with low volatility")
            return True, momentum_stats["normalised_score"]
        return False, momentum_stats["normalised_score"]
    else:
        print("Momentum found, trading without volatility")
        return True, momentum_stats["normalised_score"]

# A test to iterate through every data point in a series determining what type of pattern is being shown
# 100 periods is needed as a minimum as hurst exponent calculation requires 100 minimum
def find_periods_of_mean_rev_and_momentum(series,
                                          asset,
                                          timeframe,
                                          start_date,
                                          end_date,
                                          p_val_len_thresh,
                                          volatility_lookback,
                                          min_periods=100,
                                          print_output=False):

    i = min_periods  # Start index after enough data exists to form the first rolling window
    mean_rev_periods = []  # Stores (start_idx, end_idx) for detected mean-reversion regimes
    momentum_periods = []  # Stores (start_idx, end_idx) for detected momentum regimes
    volatility_stats = None  # Volatility stats are computed once and reused

    # Outer loop: scan forward through the series to detect regime starts
    while i < len(series):
        # Rolling window ending at index i, used to classify current regime
        window = series.iloc[i - min_periods:i]
        # Compute momentum statistics for the current window
        momentum_stats = get_momentum_statistics(window, p_val_len_thresh, asset, timeframe, start_date, end_date, print_output=print_output)
        # Compute mean-reversion statistics for the same window
        mean_rev_stats = get_series_mean_rev_stats(window, asset, timeframe, start_date, end_date, print_output=print_output)
        # Compute volatility statistics once (used for context, not regime detection)
        if volatility_stats is None:
            # Only compute once, outside the regime loop
            volatility_stats = get_volatility_statistics(series, volatility_lookback, asset, timeframe, start_date, end_date, print_output=print_output)
        # Classify the current regime based on momentum vs mean-reversion evidence
        current_pattern = determine_momentum_or_mean_rev(momentum_stats, mean_rev_stats, print_output=print_output)
        # Mark the start index of the detected regime
        start_idx = i
        # Inner loop: extend the current regime forward until classification changes
        while i < len(series):
            # Build the next rolling window one step forward
            next_window = series.iloc[i - min_periods:i]
            # Recompute statistics for the next window
            next_momentum_stats = get_momentum_statistics(next_window, p_val_len_thresh, asset, timeframe, start_date, end_date, print_output=print_output)
            next_mean_rev_stats = get_series_mean_rev_stats(next_window, asset, timeframe, start_date, end_date, print_output=print_output)
            # Classify the regime at the new position
            next_pattern = determine_momentum_or_mean_rev(next_momentum_stats, next_mean_rev_stats, print_output=print_output)
            # Stop extending the regime if classification changes
            if next_pattern != current_pattern:
                break
            # Continue extending the current regime forward
            i += 1
        # Store the detected regime period once it ends
        if current_pattern == "momentum":
            momentum_periods.append((start_idx, i - 1))
        elif current_pattern == "mean_reversion":
            mean_rev_periods.append((start_idx, i - 1))
        # Move to the next index to search for a new regime
        i += 1  # move to next starting point
    # Combine both regime types into a single labelled list
    regime_periods = [
        (start, end, "mean_reversion") for (start, end) in mean_rev_periods
    ] + [
        (start, end, "momentum") for (start, end) in momentum_periods
    ]

    return {
        "mean_reversion_periods": mean_rev_periods,
        "momentum_periods": momentum_periods,
        "regime_periods": regime_periods,
        "volatility_stats": volatility_stats
    }



