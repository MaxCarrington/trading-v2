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
def get_series_mean_rev_stats(series, asset, time_frame, date, threshold=0.05):
    close = series['Close']
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

    normalised_score = round((score / 95.0) * 100, 2)

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
        'normalised_score': normalised_score,
        'half_life_duration': half_life_duration,
        'asset': asset,
        'time_frame': time_frame,
        'date': date
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

    print(f"\n📊 **Mean Reversion Stats**")
    print(f"Asset: {stats['asset']}")
    print(f"Timeframe: {stats['time_frame']}")
    print(f"Date: {stats['date']}")
    print("-" * 50)

    # --- Hurst Exponent ---
    print("\n📈 Hurst Exponent:")
    print(f"  - Value: {attrs['h_val']['hurst']}")
    print(f"  - Classification: {attrs['h_val']['classification']}")

    # --- Variance Ratio Test ---
    vr = attrs['vr_result']
    vr_stats = vr.get('Stats', {})

    print("\n🔁 Variance Ratio Test:")
    print(f"  - Significant         : {vr.get('Significant')}")
    print(f"  - Lag Used            : {vr.get('Lag')}")
    print(f"  - Reason              : {vr.get('Reason', 'N/A')}")
    if vr_stats:
        print(f"     • Test Statistic   : {vr_stats.get('stat', 'N/A'):.4f}")
        print(f"     • p-value          : {vr_stats.get('p_value', 'N/A'):.4f}")
        print(f"     • Variance Ratio   : {vr_stats.get('vr', 'N/A'):.4f}")
    else:
        print("     • No valid statistics returned.")

    # --- ADF Test ---
    adf = attrs['adf_result']
    print("\n🧮 ADF Test:")
    print(f"  - Stationarity Detected: {adf['is_stationary']}")
    print(f"  - ADF Statistic: {adf['adf_statistic']:.4f}")
    print(f"  - p-value: {adf['p_value']:.4f}")
    print(f"  - Used Lag: {adf['used_lag']}")
    print(f"  - Observations: {adf['n_obs']}")
    print("  - Critical Values:")
    for k, v in adf['critical_values'].items():
        print(f"      • {k}: {v:.4f}")
    print(f"  - Best IC (AIC/BIC): {adf['ic_best']:.4f}")

    # --- Half-Life ---
    hl = attrs['half_life']
    print("\n⏳ Half-Life of Mean Reversion:")
    print(f"  - With Intercept: {hl['HalfLife_WithIntercept']:.4f}")
    print(f"  - No Intercept:   {hl['HalfLife_NoIntercept']:.4f}")
    print(f"  - Duration Category: {stats['half_life_duration']}")

    # --- Component Scores ---
    comp = stats['component_scores']
    print("\n🧩 Component Scores:")
    print(f"  - Hurst:     {comp['hurst']:.2f}")
    print(f"  - VR:        {comp['vr']:.2f}")
    print(f"  - ADF:       {comp['adf']:.2f}")
    print(f"  - Half-Life: {comp['half_life']:.2f}")

    # --- Final Score ---
    # --- Final Score ---
    print("\n🏁 Final Mean Reversion Summary:")
    print(f"  - Total Raw Score       : {stats['mean_rev_score']} / 95")
    print(f"  - Normalized Score      : {stats['normalized_score']:.2f} / 100")
    print("\n🔍 Score Breakdown:")

    # Hurst
    hurst_class = attrs['h_val']['classification']
    hurst_score = comp['hurst'] * 20
    print(f"  • Hurst Exponent        : {hurst_class} → +{int(hurst_score)} points")

    # Variance Ratio
    vr_reason = vr.get('Reason', 'N/A')
    vr_score = comp['vr'] * 15
    print(f"  • Variance Ratio        : {vr_reason} → +{int(vr_score)} points")

    # ADF
    adf_pval = adf['p_value']
    adf_score = comp['adf'] * 20
    adf_reason = "Stationary" if adf_pval < 0.05 else "Non-stationary"
    print(f"  • ADF Test              : {adf_reason} (p={adf_pval:.4f}) → +{int(adf_score)} points")

    # Half-Life
    hl_category = stats['half_life_duration']
    hl_score = comp['half_life'] * 20
    print(f"  • Half-Life Duration    : {hl_category} → +{int(hl_score)} points")

    # Bonus
    bonus = stats['mean_rev_score'] - (hurst_score + vr_score + adf_score + hl_score)
    if bonus > 0:
        print(f"  • Full Agreement Bonus  : +{bonus} points")

    # Verdict
    score = stats['normalized_score']
    if score >= 85:
        verdict = "✅ Strong Mean-Reversion Candidate"
    elif score >= 65:
        verdict = "⚠️  Moderate Mean-Reversion Potential"
    elif score >= 40:
        verdict = "❓ Weak Mean-Reversion Signal"
    else:
        verdict = "❌ Not Suitable for Mean-Reversion Strategy"

    print(f"\n🧠 Verdict                : {verdict}")
    print("-" * 50)


