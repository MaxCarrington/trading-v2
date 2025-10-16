from src.trading.data.data_analysis.mean_rev_analysis import get_series_mean_rev_stats, print_mean_rev_summary
from src.trading.data.data_analysis.momentum_analysis import get_momentum_statistics, print_momentum_statistics
from src.trading.data.data_analysis.volatility_analysis import analyse_period_volatility, print_volatility_analysis
from src.trading.data.data_analysis.volume_analysis import combined_liquidity_analysis, print_liquidity_analysis
from src.trading.utils.config import load_strategy_configs

MINIMUM_STRATEGY_THRESHOLD = 50
# Perform data analysis to generate mean-reversion, momentum, volatility and volume data
def perform_analysis(series, asset, timeframe, date, is_forex=False):
    # Load in the config files
    thresholds, analysis_params, setup_params, labels = load_strategy_configs()

    liquidity_stats = None
    # Generate strategy data analysis
    momentum_stats = get_momentum_statistics(series, analysis_params["momentum"]["window_size"], asset, timeframe, date)
    mean_rev_stats = get_series_mean_rev_stats(series, asset, timeframe, date)
    volatility_stats = analyse_period_volatility(series, analysis_params["volatility"]["lookback"], asset, timeframe, date)

    if not is_forex:
        liquidity_stats = combined_liquidity_analysis(series, asset, timeframe, date)

    determine_best_strategy(momentum_stats, mean_rev_stats, volatility_stats, liquidity_stats)

# Determines the best strategy to used between normalised (z-score) data analysis results
def determine_best_strategy(momentum_stats, mean_rev_stats, volatility_stats=None, liquidity_stats=None, print_output=False):

    mr_z_score = mean_rev_stats['normalised_score']
    momentum_z_score = momentum_stats['normalised_score']

    if mr_z_score >= MINIMUM_STRATEGY_THRESHOLD and mr_z_score > momentum_z_score:
        verdict = "✅ Mean-Reversion Selected"
        strategy = "mean_reversion"
    elif momentum_z_score >= MINIMUM_STRATEGY_THRESHOLD and momentum_z_score > mr_z_score:
        verdict = "✅ Momentum Selected"
        strategy = "momentum"
    else:
        verdict = "❌ No Suitable Strategy"
        strategy = "none"

    if print_output:
        print(f"\n🧠 Strategy Verdict: {verdict}")
        print("-" * 50)

    return strategy

# A test to iterate through every data point in a series determining what type of pattern is being shown
def rolling_analysis(series, asset, timeframe, date, min_periods=100):
    thresholds, analysis_params, setup_params, labels = load_strategy_configs()

    i = min_periods
    mean_rev_periods = []
    momentum_periods = []

    while i < len(series):
        window = series.iloc[i - min_periods:i]
        momentum_stats = get_momentum_statistics(window, analysis_params["momentum"]["window_size"], asset, timeframe, date)
        mean_rev_stats = get_series_mean_rev_stats(window, asset, timeframe, date)
        current_pattern = determine_best_strategy(momentum_stats, mean_rev_stats)

        start_idx = i
        while i < len(series):
            next_window = series.iloc[i - min_periods:i]
            next_momentum_stats = get_momentum_statistics(next_window, analysis_params["momentum"]["window_size"], asset, timeframe, date)
            next_mean_rev_stats = get_series_mean_rev_stats(next_window, asset, timeframe, date)
            next_pattern = determine_best_strategy(next_momentum_stats, next_mean_rev_stats)

            if next_pattern != current_pattern:
                break
            i += 1

        if current_pattern == "momentum":
            momentum_periods.append((start_idx, i - 1))
        elif current_pattern == "mean_reversion":
            mean_rev_periods.append((start_idx, i - 1))

        i += 1  # move to next starting point

    regime_periods = [
                         (start, end, "mean_reversion") for (start, end) in mean_rev_periods
                     ] + [
                         (start, end, "momentum") for (start, end) in momentum_periods
                     ]


    return {
        "mean_reversion_periods": mean_rev_periods,
        "momentum_periods": momentum_periods
    }






