import pandas as pd
import numpy as np
import statsmodels.api as sm
from trading.data.stat_tests.augmented_dickey_fuller import perform_adf_test
from trading.data.stat_tests.hurst_exponent import calculate_hurst_exponent
from trading.data.stat_tests.variance_ratio_test import perform_variance_ratio_test
from trading.utils.logger import start_log, info, warning, error

#  Calculates mean reversion statistics
#   - Calculate the variance ratio for each time series
#   - Calculate the half life of mean-reversion
#   - Calculate the ADF test
#   - Calculate the Hurst exponent
#   - Score each time series out of 100 based on above
#   - If score is higher than the set amount, the time series will be used for
#     mean reversion
def get_series_mean_rev_stats(series, asset, time_frame, start_date, end_date, threshold=0.05, info_output=False):

    return 10

# Calculation of the half life of mean reversion for a given time series

# The half life of mean reversion is used to determine the time it takes for an
# asset's price to return halfway to its historical average after deviating from
# it. If the half-life is low, the asset mean reverts frequently and the mean
# reversion does not take a long time. Otherwise, if the half-life were long,
# this would render the strategy less useful as it cannot profit regularly.

# Code adapted from: https://flare9xblog.wordpress.com/2017/09/27/half-life-of-mean
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

# infos mean reversion statistics in a readable manner
def info_mean_rev_analysis(stats):
    attrs = stats['attributes']

    info(f"\n\n\n📊 **Mean Reversion Stats**")
    info(f"Asset: {stats['asset']}")
    info(f"Timeframe: {stats['time_frame']}")
    info(f"Start Date: {stats['start_date']}")
    info(f"End Date: {stats['end_date']}")
    info("-" * 50)

    # --- Hurst Exponent ---
    info("📈 Hurst Exponent:")
    info(f"  - Value: {attrs['h_val']['hurst']}")
    info(f"  - Classification: {attrs['h_val']['classification']}")

    # --- Variance Ratio Test ---
    vr = attrs['vr_result']
    vr_stats = vr.get('Stats', {})

    info("🔁 Variance Ratio Test:")
    info(f"  - Significant         : {vr.get('Significant')}")
    info(f"  - Lag Used            : {vr.get('Lag')}")
    info(f"  - Reason              : {vr.get('Reason', 'N/A')}")
    if vr_stats:
        info(f"     • Test Statistic   : {vr_stats.get('stat', 'N/A'):.4f}")
        info(f"     • p-value          : {vr_stats.get('p_value', 'N/A'):.4f}")
        info(f"     • Variance Ratio   : {vr_stats.get('vr', 'N/A'):.4f}")
    else:
        info("     • No valid statistics returned.")

    # --- ADF Test ---
    adf = attrs['adf_result']
    info("🧮 ADF Test:")
    info(f"  - Stationarity Detected: {adf['is_stationary']}")
    info(f"  - ADF Statistic: {adf['adf_statistic']:.4f}")
    info(f"  - p-value: {adf['p_value']:.4f}")
    info(f"  - Used Lag: {adf['used_lag']}")
    info(f"  - Observations: {adf['n_obs']}")
    info("  - Critical Values:")
    for k, v in adf['critical_values'].items():
        info(f"      • {k}: {v:.4f}")
    info(f"  - Best IC (AIC/BIC): {adf['ic_best']:.4f}")

    # --- Half-Life ---
    hl = attrs['half_life']
    info("⏳ Half-Life of Mean Reversion:")
    info(f"  - With Intercept: {hl['HalfLife_WithIntercept']:.4f}")
    info(f"  - No Intercept:   {hl['HalfLife_NoIntercept']:.4f}")
    info(f"  - Duration Category: {stats['half_life_duration']}")

    # --- Component Scores ---
    comp = stats['component_scores']
    info("🧩 Component Scores:")
    info(f"  - Hurst:     {comp['hurst']:.2f}")
    info(f"  - VR:        {comp['vr']:.2f}")
    info(f"  - ADF:       {comp['adf']:.2f}")
    info(f"  - Half-Life: {comp['half_life']:.2f}")

    # --- Final Score ---
    info("🏁 Final Mean Reversion Summary:")
    info(f"  - Total Raw Score       : {stats['mean_rev_score']} / 95")
    info(f"  - Normalised Score      : {stats['normalised_score']:.2f} / 100")
    info("🔍 Score Breakdown:")

    # Hurst
    hurst_class = attrs['h_val']['classification']
    hurst_score = comp['hurst'] * 20
    info(f"  • Hurst Exponent        : {hurst_class} → +{int(hurst_score)} points")

    # Variance Ratio
    vr_reason = vr.get('Reason', 'N/A')
    vr_score = comp['vr'] * 15
    info(f"  • Variance Ratio        : {vr_reason} → +{int(vr_score)} points")

    # ADF
    adf_pval = adf['p_value']
    adf_score = comp['adf'] * 20
    adf_reason = "Stationary" if adf_pval < 0.05 else "Non-stationary"
    info(f"  • ADF Test              : {adf_reason} (p={adf_pval:.4f}) → +{int(adf_score)} points")

    # Half-Life
    hl_category = stats['half_life_duration']
    hl_score = comp['half_life'] * 20
    info(f"  • Half-Life Duration    : {hl_category} → +{int(hl_score)} points")

    # Bonus
    bonus = stats['mean_rev_score'] - (hurst_score + vr_score + adf_score + hl_score)
    if bonus > 0:
        info(f"  • Full Agreement Bonus  : +{bonus} points")

    # Verdict
    score = stats['normalised_score']
    if score >= 85:
        verdict = "✅ Strong Mean-Reversion Candidate"
    elif score >= 65:
        verdict = "⚠️  Moderate Mean-Reversion Potential"
    elif score >= 40:
        verdict = "❓ Weak Mean-Reversion Signal"
    else:
        verdict = "❌ Not Suitable for Mean-Reversion Strategy"

    info(f"🧠 Verdict                : {verdict}")
    info("-" * 50)


