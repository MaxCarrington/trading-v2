import numpy as np
import pandas as pd
from scipy.stats import pearsonr

from src.trading.data.stat_tests.augmented_dickey_fuller import perform_adf_test
from src.trading.utils.data_manipulation import to_log_returns
from src.trading.data.stat_tests.hurst_exponent import calculate_hurst_exponent

# Get the momentum statistical information from analysis
def get_momentum_statistics(series, length_threshold):
    log_returns = to_log_returns(series['Close'].dropna())
    rolling_correlations = calc_optimal_window_size(log_returns)
    momentum_indication = check_len_for_momentum(length_threshold, rolling_correlations)
    normalised_stat_score = statistical_score(series) / 100
    if momentum_indication == "Momentum" and normalised_stat_score > 0.99:
        suitability = "Very high"
    elif momentum_indication == "Mean-Reversion" and normalised_stat_score < 0.01:
        suitability = "Very low"
    elif momentum_indication == "Momentum" and normalised_stat_score >= 0.5:
        suitability = "Moderate"
    else:
        suitability = "Low"

    regime_weight = {
        "Momentum": 1.0,
        "Mean-Reversion": -1.0,
        "None": 0.0,
        "Insufficient Data": 0.0
    }
    strength = abs(rolling_correlations.get('best_correlation'))
    reliability = min(1.0, len(rolling_correlations.get('correlations', [])) / rolling_correlations.get('max_possible_windows', 1))

    # Value consistency over intensity
    confidence = 0.4 * strength + 0.6 * reliability

    combined_score = normalised_stat_score * (regime_weight.get(momentum_indication, 0.0)) * confidence
    return {
        'normalised_stat_score': normalised_stat_score,
        'combined_score': combined_score,
        'momentum_suitability': suitability,
        'momentum_indication': momentum_indication,
        'lookback': rolling_correlations.get('lookback'),
        'best_correlation': rolling_correlations.get('best_correlation'),
        'correlations': rolling_correlations
    }

# Calculate the correlation between past and future returns of given (rolling) windows of a time series
# and the dates of each window
def calculate_rolling_correlations(series, window_size, significance_level=0.05):
    log_returns = series.dropna()

    total_length = len(log_returns)
    window_size = min(window_size, total_length // 2)

    correlations = []
    start_date_past = []
    start_date_future = []

    for i in range(total_length - 2 * window_size + 1):
        past_returns = log_returns.iloc[i: i + window_size]
        future_returns = log_returns.iloc[i + window_size: i + 2 * window_size]

        if len(past_returns) == len(future_returns):
            corr, p_value = pearsonr(past_returns, future_returns)
            if not np.isnan(corr) and p_value < significance_level:
                correlations.append(corr)
                start_date_past.append(past_returns.index[0])
                start_date_future.append(future_returns.index[0])
    return {
        'correlations': correlations,
        'start_date_past': start_date_past,
        'start_date_future': start_date_future
    }

# Finds the optimal rolling window size that yields the highest significant correlation
# between past and future log returns.
def calc_optimal_window_size(series, start_window_size = 10, end_window_size = 40, step_size = 2, significance_level = 0.05):
    best_correlation = -np.inf
    optimal_window_size = None
    correlation_result = {}
    total_possible_windows = 0
    for window_size in range(start_window_size, end_window_size + 1, step_size):
        window_count = len(series) - 2 * window_size + 1
        if window_count > 0:
            total_possible_windows += window_count
            corr_res = calculate_rolling_correlations(series, window_size, significance_level)
            if corr_res['correlations']:
                max_corr = max(corr_res['correlations'])
                if max_corr > best_correlation:
                    best_correlation = max_corr
                    correlation_result = corr_res
                    optimal_window_size = window_size

    return {
        'lookback': optimal_window_size,
        'best_correlation': best_correlation,
        'correlations': correlation_result.get('correlations', []),
        'start_date_past': correlation_result.get('start_date_past', []),
        'start_date_future': correlation_result.get('start_date_future', []),
        'max_possible_windows': total_possible_windows
    }

# Classifies regime based on proportion of positive vs. negative correlations.
def check_len_for_momentum(length_thresh, correlation_dict):
    print(correlation_dict)
    correlations = np.array(correlation_dict.get('correlations', []))
    if len(correlations) == 0:
        return "Insufficient Data"

    num_positives = np.sum(correlations > 0)
    num_negatives = np.sum(correlations < 0)
    total = len(correlations)

    if num_positives >= total * length_thresh:
        return "Momentum"
    elif num_negatives >= total * length_thresh:
        return "Mean-Reversion"
    else:
        return "None"

# Checks if a time series is stationary using the ADF test.
# Expects a DataFrame with a 'Close' column.
def check_stationarity(series, significance_level=0.05):
    adf_result = perform_adf_test(series['Close'], significance_level)
    if adf_result['is_stationary'] is True:
        return True
    else:
        return False

def statistical_score(series):
    adf_result = perform_adf_test(series['Close'])
    hurst_result = calculate_hurst_exponent(series['Close'])

    is_stationary = adf_result.get('is_stationary', True)
    hurst_class = hurst_result.get('classification', 'undefined')

    # Scoring logic
    if not is_stationary and hurst_class == 'trending':
        score = 100  # strongest momentum signal
    elif not is_stationary and hurst_class == 'random_walk':
        score = 70  # possible drift, weak trend
    elif is_stationary and hurst_class == 'trending':
        score = 50  # trending within stationary bounds
    elif not is_stationary and hurst_class == 'mean_reverting':
        score = 30  # volatile but not directional
    else:
        score = 0  # not suitable for momentum

    return score

def print_momentum_statistics(stats_dict):
    """
    Neatly prints the output from get_momentum_statistics.
    """
    print("\n📊 Momentum Diagnostic Summary")
    print("-" * 40)
    print(f"Momentum Suitability     : {stats_dict.get('momentum_suitability', 'N/A')}")
    print(f"Momentum Indication      : {stats_dict.get('momentum_indication', 'N/A')}")
    print(f"Statistical Score        : {stats_dict.get('normalised_stat_score', 0):.2f}")
    print(f"Combined Score           : {stats_dict.get('combined_score', 0):.2f}")
    print(f"Optimal Lookback Window  : {stats_dict.get('lookback', 'N/A')}")
    print(f"Best Correlation         : {stats_dict.get('best_correlation', 'N/A'):.4f}")
    print(f"Significant Correlations : {len(stats_dict.get('correlations', []))}")
    print("-" * 40)

    # Optional: show sample dates
    past_dates = stats_dict.get('correlations', {}).get('start_date_past', [])
    future_dates = stats_dict.get('correlations', {}).get('start_date_future', [])
    if past_dates and future_dates:
        print("🕒 Sample Window Dates")
        for i in range(min(3, len(past_dates))):
            print(f"  Past: {past_dates[i]} → Future: {future_dates[i]}")
        print("-" * 40)
