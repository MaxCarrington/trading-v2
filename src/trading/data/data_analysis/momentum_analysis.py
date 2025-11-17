import sys

import numpy as np
from scipy.stats import pearsonr

from src.trading.data.stat_tests.augmented_dickey_fuller import perform_adf_test
from src.trading.utils.data_manipulation import to_log_returns
from src.trading.data.stat_tests.hurst_exponent import calculate_hurst_exponent

# Get the momentum statistical information from analysis
def get_momentum_statistics(series, length_threshold, asset, time_frame, date):
    log_returns = to_log_returns(series['Close'].dropna().tail(75))

    # find the optimal lookback window with strongest correlation signal
    rolling_correlations = calc_optimal_window_size(log_returns)

    # Use only optimal correlations for regime classification
    optimal_corrs = rolling_correlations.get('correlations', [])

    # classify regime (Momentum/Mean-Reversion/None) based on correlation outcomes
    momentum_indication = check_len_for_momentum(length_threshold, {'correlations': optimal_corrs})

    #print(f"momentum indication:{momentum_indication}")

    normalised_score, suitability = generate_momentum_score(momentum_indication, rolling_correlations)

    return {
        'normalised_score': normalised_score,
        'momentum_suitability': suitability,
        'momentum_indication': momentum_indication,
        'lookback': rolling_correlations.get('lookback'),
        'best_correlation': rolling_correlations.get('best_correlation'),
        'correlations': rolling_correlations,
        'asset': asset,
        'time_frame': time_frame,
        'date': date
    }

# Generates a momentum score
def generate_momentum_score(momentum_indication, rolling_correlations):
    strength = abs(rolling_correlations.get('best_correlation', 0.0))

    # Only score if regime indicates Momentum
    if momentum_indication == "Momentum":
        normalised_score = round(strength * 100, 2)
        suitability = "Momentum"
    elif momentum_indication == "Mean-Reversion":
        normalised_score = round((1 - strength) * 100, 2)
        suitability = "Mean-Reversion"
    else:
        normalised_score = 0
        suitability = "None"

    return normalised_score, suitability


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
def calc_optimal_window_size(series, start_window_size = 10, end_window_size = 60, step_size = 2, significance_level = 0.05):
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
    # Extract correlation values from dictionary (default to empty list if missing)
    correlations = np.array(correlation_dict.get('correlations', []), dtype=float)

    # If no correlations are available, return insufficient data
    if len(correlations) == 0:
        return "Insufficient Data"

    # Count how many correlations are positive (momentum) and negative (mean-reversion)
    num_positives = np.sum(correlations > 0)
    num_negatives = np.sum(correlations < 0)
    total = len(correlations)

    # If positives exceed threshold proportion, classify as Momentum
    if num_positives >= total * length_thresh:
        return "Momentum"
    # If negatives exceed threshold proportion, classify as Mean-Reversion
    elif num_negatives >= total * length_thresh:
        return "Mean-Reversion"
    # Otherwise, no clear regime detected
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

# Generates a score based on the statistical analysis used
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

# Neatly prints the output from get_momentum_statistics
def print_momentum_statistics(stats_dict):
    print("\n📊 Momentum Diagnostic Summary")
    print(f"Asset: {stats_dict.get('asset')}")
    print(f"Date: {stats_dict.get('date')}")
    print(f"Timeframe: {stats_dict.get('time_frame')}")
    print("-" * 50)

    # --- Regime Classification ---
    indication = stats_dict.get('momentum_indication', 'N/A')
    suitability = stats_dict.get('momentum_suitability', 'N/A')
    print("\n🔁 Regime Classification:")
    print(f"  • Momentum Indication   : {indication}")
    print(f"  • Suitability Rating    : {suitability}")

    # --- Statistical Score ---
    stat_score = stats_dict.get('normalised_stat_score', 0)
    print("\n📐 Statistical Score:")
    print(f"  • Normalised Score      : {stat_score:.2f} / 1.00")

    # --- Correlation Diagnostics ---
    lookback = stats_dict.get('lookback', 'N/A')
    best_corr = stats_dict.get('best_correlation', 0)
    corr_list = stats_dict.get('correlations', {}).get('correlations', [])
    reliability = min(1.0, len(corr_list) / stats_dict.get('correlations', {}).get('max_possible_windows', 1))
    strength = abs(best_corr)
    print("\n📈 Correlation Diagnostics:")
    print(f"  • Optimal Lookback      : {lookback}")
    print(f"  • Best Correlation      : {best_corr:.4f}")
    print(f"  • Strength              : {strength:.2f}")
    print(f"  • Reliability           : {reliability:.2f}")
    print(f"  • Significant Windows   : {len(corr_list)}")

    # --- Combined Score ---
    combined_score = stats_dict.get('combined_score', 0)
    print("\n🧮 Combined Momentum Score:")
    print(f"  • Score = stat × regime weight × confidence")
    print(f"  • Final Combined Score  : {combined_score:.2f}")

    # --- Confidence Breakdown ---
    print("\n🔍 Confidence Breakdown:")
    print(f"  • Strength Component    : {strength:.2f}")
    print(f"  • Reliability Component : {reliability:.2f}")
    print(f"  • Weighted Confidence   : {0.4 * strength + 0.6 * reliability:.2f}")

    # --- Sample Dates ---
    past_dates = stats_dict.get('correlations', {}).get('start_date_past', [])
    future_dates = stats_dict.get('correlations', {}).get('start_date_future', [])
    if past_dates and future_dates:
        print("\n🕒 Sample Window Dates:")
        for i in range(min(3, len(past_dates))):
            print(f"  • Past: {past_dates[i]} → Future: {future_dates[i]}")
    print("-" * 50)

    # --- Verdict ---
    if suitability == "Very high":
        verdict = "✅ Strong Momentum Candidate"
    elif suitability == "Moderate":
        verdict = "⚠️  Moderate Momentum Potential"
    elif suitability == "Low":
        verdict = "❓ Weak Momentum Signal"
    else:
        verdict = "❌ Not Suitable for Momentum Strategy"

    print(f"\n🧠 Verdict: {verdict}")
    print("-" * 50)

