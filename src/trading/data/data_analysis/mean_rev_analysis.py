import pandas as pd
import numpy as np
import statsmodels.api as sm
from src.trading.data.stat_tests.augmented_dickey_fuller import perform_adf_test
from src.trading.data.stat_tests.hurst_exponent import calculate_hurst_exponent
from src.trading.data.stat_tests.variance_ratio_test import perform_variance_ratio_test
#-------------------------------------------------------------------------------
#  Calculates mean reversion statistics
#   - Calculate the variance ratio for each time series
#   - Calculate the half life of mean-reversion
#   - Calculate the ADF test
#   - Calculate the Hurst exponent
#   - Score each time series out of 100 based on above
#   - If score is higher than the set amount, the time series will be used for
#     mean reversion
#-------------------------------------------------------------------------------
def get_series_mean_rev_stats(series_df, index, threshold=0.05):
    close = series_df['Close']
    score = 0
    consistency = 0

    # --- Run diagnostics ---
    h_val = calculate_hurst_exponent(close)
    vr_result = perform_variance_ratio_test(close)
    adf_result = perform_adf_test(close)
    half_life = calculate_half_life(close)

    # --- Scoring logic ---
    def score_hurst(h):
        if h['classification'] == 'mean_reverting':
            return 20, True
        else:
            return 0, False

    def score_vr(vr):
        return (15, True) if vr.get('significant') else (0, False)

    def score_adf(adf):
        pval = adf.get('p_value')
        return (20, True) if pval is not None and pval < threshold else (0, False)

    # Apply scoring
    print(h_val)
    hurst_score, hurst_consistent = score_hurst(h_val)
    vr_score, vr_consistent = score_vr(vr_result)
    adf_score, adf_consistent = score_adf(adf_result)

    score += hurst_score + vr_score + adf_score
    consistency += sum([hurst_consistent, vr_consistent, adf_consistent])

    # --- Half-life scoring ---
    attributes = {
        'h_val': h_val,
        'vr_result': vr_result,
        'adf_result': adf_result,
        'half_life': half_life
    }

    half_life_duration = determine_half_life_quantile(attributes)
    half_life_score = calc_half_life_score(half_life_duration)
    score += half_life_score

    # --- Bonus for full agreement ---
    if score > 0 and consistency == 3:
        score += 20

    normalized_score = round((score / 95.0) * 100, 2)

    component_scores = {
        'hurst': hurst_score / 20,
        'vr': vr_score / 15,
        'adf': adf_score / 20,
        'half_life': half_life_score / 20
    }

    return {
        'attributes': attributes,
        'mean_rev_score': score,
        'component_scores': component_scores,
        'normalized_score': normalized_score,
        'half_life_duration': half_life_duration,
        'series_index': index
    }

#-------------------------------------------------------------------------------
# Calculation of the half life of mean reversion for a given time series

# The half life of mean reversion is used to determine the time it takes for an
# asset's price to return halfway to its historical average after deviating from
# it. If the half-life is low, the asset mean reverts frequently and the mean
# reversion does not take a long time. Otherwise, if the half-life were long,
# this would render the strategy less useful as it cannot profit regularly.

# Code taken from: https://flare9xblog.wordpress.com/2017/09/27/half-life-of-mean
#-reversion-ornstein-uhlenbeck-formula-for-mean-reverting-process/
# The functionality of the code taken from the link has been changed to work for
# the OHLCV format

# Acceptable values:
# Short Half-life: 1-15 periods
# Medium half life: 15-32 periods
# Long half life: 32-52 periods
def calculate_half_life(series):
    series = pd.Series(series).dropna()

    # Lagged series
    y_lag = series.shift(1).dropna()
    y = series.iloc[1:len(y_lag)+1]  # align with y_lag
    y_diff = y - y_lag

    # Mean-adjusted lagged values
    prev_y_mean = y_lag - y_lag.mean()

    # Trim to match lengths
    y_diff = y_diff.iloc[:len(prev_y_mean)]
    prev_y_mean = prev_y_mean.iloc[:len(y_diff)]

    # --- Regression with intercept ---
    X1 = sm.add_constant(prev_y_mean)
    model1 = sm.OLS(y_diff, X1).fit()
    beta1 = model1.params.iloc[1]
    half_life_with_intercept = -np.log(2) / beta1 if beta1 != 0 else np.inf

    # --- Regression without intercept ---
    X2 = prev_y_mean.values.reshape(-1, 1)
    model2 = sm.OLS(y_diff, X2).fit()
    beta2 = model2.params.iloc[0]
    half_life_no_intercept = -np.log(2) / beta2 if beta2 != 0 else np.inf

    return {
        'HalfLife_WithIntercept': half_life_with_intercept,
        'HalfLife_NoIntercept': half_life_no_intercept
    }

def determine_half_life_quantile(attributes, reference_distribution=None):
    if reference_distribution is not None:
        q25 = np.percentile(reference_distribution, 25)
        q50 = np.percentile(reference_distribution, 50)
        q75 = np.percentile(reference_distribution, 75)
        hl_with = attributes['half_life']['HalfLife_WithIntercept']
        hl_without = attributes['half_life']['HalfLife_NoIntercept']

        if hl_with < q25 or hl_without < q25:
            return "SHORT"
        elif hl_with < q50 or hl_without < q50:
            return "MEDIUM"
        elif hl_with < q75 or hl_without < q75:
            return "LONG"
        else:
            return "TOO_LONG"
    else:
        short_boundary = 15
        medium_boundary = 32
        long_boundary = 52
        print(attributes)
        hl_with = attributes['half_life']['HalfLife_WithIntercept']
        hl_without = attributes['half_life']['HalfLife_NoIntercept']
        if hl_with < short_boundary or hl_without < short_boundary:
            return "SHORT"
        elif hl_with < medium_boundary or hl_without < medium_boundary:
            return "MEDIUM"
        elif hl_with < long_boundary or hl_without < long_boundary:
            return "LONG"
        else:
            return "TOO_LONG"

# Based on the half life duration, generate a score
def calc_half_life_score(duration_label):
    scores = {
        "SHORT": 25,
        "MEDIUM": 15,
        "LONG": 5,
        "TOO_LONG": 0
    }
    return scores.get(duration_label, None)

# Prints mean reversion statistics in a readable manner
def print_mean_rev_summary(stats):
    attrs = stats['attributes']
    print(f"\nMean Reversion Stats (Series Index: {stats['series_index']})")
    print("-" * 40)
    print(f"Hurst Exponent: {attrs['h_val']['hurst']}")
    print(f"Hurst Exponent classficiation: {attrs['h_val']['classification']}")

    vr = attrs['vr_result']
    print("\nVariance Ratio Test:")
    print(f"  - Significant: {vr['Significant']}")
    print(f"  - Lag: {vr['Lag']}")
    print(f"  - Stats: {vr['Stats']}")

    adf = attrs['adf_result']
    print("\nADF Test:")
    print(f"Test found stationarity was: {adf['is_stationary']}")
    print(f"  - ADF Statistic: {adf['adf_statistic']:.4f}")
    print(f"  - p-value: {adf['p_value']:.4f}")
    print(f"  - Used Lag: {adf['used_lag']}")
    print(f"  - Observations: {adf['n_obs']}")
    print("  - Critical Values:")
    for k, v in adf['critical_values'].items():
        print(f"      - {k}: {v:.4f}")
    print(f"  - Best IC (AIC/BIC): {adf['ic_best']:.4f}")

    hl = attrs['half_life']
    print("\nHalf-Life of Mean Reversion:")
    print(f"  - With Intercept: {hl['HalfLife_WithIntercept']:.4f}")
    print(f"  - No Intercept:   {hl['HalfLife_NoIntercept']:.4f}")
    print(f"  - Duration Category: {stats['half_life_duration']}")

    comp = stats['component_scores']
    print("\nComponent Scores:")
    print(f"  - Hurst:     {comp['hurst']:.2f}")
    print(f"  - VR:        {comp['vr']:.2f}")
    print(f"  - ADF:       {comp['adf']:.2f}")
    print(f"  - Half-Life: {comp['half_life']:.2f}")

    print(f"\nTotal Mean Reversion Score: {stats['mean_rev_score']}")
    print(f"Normalized Score (0–100): {stats['normalized_score']:.2f}")
