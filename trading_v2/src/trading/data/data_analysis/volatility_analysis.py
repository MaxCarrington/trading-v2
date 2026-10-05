import numpy as np
import pandas as pd
from collections import Counter
from trading.indicators.average_true_range import calculate_rolling_atr
from trading.utils.data_manipulation import zscore_standardisation
from trading.utils.logger import start_log, info, warning, error

# Function uses Average True Range, Standard Deviation
# to determine the volatility over a given period
#
# classification_lookback: size of the TRAILING reference window used to
# decide what counts as high/low volatility (see classify_volatility below).
# This is independent of, and normally much bigger than, `lookback` (which
# just controls the ATR/stddev smoothing period). Left as None, it defaults
# to 20x `lookback` so the reference window scales automatically with
# whatever timeframe/indicator lookback this is already configured for —
# pass an explicit value to tune it directly.
def get_volatility_statistics(series, lookback, asset, time_frame, start_date, end_date,
                               info_output=False, classification_lookback=None):
    if classification_lookback is None:
        classification_lookback = lookback * 20

    std_dev = stddev_rolling_window(series, lookback)
    # Standardise ATR, and StdDev
    standardised_atrs = zscore_standardisation(calculate_rolling_atr(series, lookback))
    standardised_std_dev = zscore_standardisation(std_dev)

    # Combine indicators into one composite measure
    combined_score = zscore_standardisation(std_atr_stddev(standardised_atrs, standardised_std_dev))
    vol_classifications = classify_volatility(combined_score, lookback=classification_lookback)
    # Calculate overall and period volatility based on periods
    series_vol = analyse_series_vol(vol_classifications)

    volatility_stats = {
        "combined_score": combined_score,
        "period_vol": vol_classifications,
        "series_vol": series_vol,
        "std_atrs": standardised_atrs,
        "stddev": standardised_std_dev,
        'asset': asset,
        'time_frame': time_frame,
        'start_date': start_date,
        'end_date': end_date,
    }

    if info_output:
        info_volatility_analysis(volatility_stats)

    return volatility_stats

# Given the monthly volatilities, determine the overall volatility of a time series
def analyse_series_vol(monthly_volatility):
    # Define category labels
    non_volatile = "Non-Volatile"
    volatile = "Volatile"
    highly_volatile = "Highly Volatile"

    # Count occurrences of each volatility category
    freq = Counter(monthly_volatility)

    # Total number of periods
    total_scores = sum(freq.values())

    # Access frequency counts safely
    num_non_volatile = freq.get("Low", 0)
    num_volatile = freq.get("Medium", 0) + freq.get("High", 0)
    num_highly_volatile = freq.get("Highly Volatile", 0)

    # Classification logic based on the distribution
    if num_non_volatile >= total_scores * 0.70:
        return non_volatile
    elif num_highly_volatile / total_scores > 0.10:
        return highly_volatile
    else:
        return volatile

# Determines the volatility classification of a specific period in time
def determine_period_volatility(classified_volatility):
    # Count occurrences of each volatility category
    freq = Counter(classified_volatility)

    # Retrieve counts (default to 0 if not present)
    num_high = freq.get("High", 0)
    num_highly_volatile = freq.get("Highly Volatile", 0)

    # Determine overall volatility based on counts
    if num_highly_volatile >= 2 or num_high > 2:
        return "Highly Volatile"
    elif num_high >= 2:
        return "Volatile"
    else:
        return "Non-Volatile"

# Classify volatility periods based on percentiles and standard deviations,
# measured against a TRAILING `lookback` window ending at each point — not
# the whole history to date.
#
# Using the full expanding history (the previous behaviour) means the
# reference mean/std/percentiles keep drifting as more bars accumulate: an
# early calm or violent stretch permanently skews what counts as "High" for
# the rest of the run, classifications stop being regime-adaptive, and the
# per-bar cost grows with total history length (recomputed over everything,
# every bar — the same scaling problem update_atr_incremental was written
# to avoid for ATR itself). A fixed trailing window fixes all three: it's
# regime-adaptive, constant-cost per bar, and behaves identically in
# backtest and live (live can only ever look backwards anyway).
#
# Bars before `lookback` valid observations have accumulated default to
# "Low" — there isn't enough trailing history yet to say anything about the
# current regime.
def classify_volatility(volatility_scores, lookback=252):
    s = pd.Series(volatility_scores)

    rolling_mean = s.rolling(window=lookback, min_periods=lookback).mean()
    rolling_sd = s.rolling(window=lookback, min_periods=lookback).std(ddof=1)  # sample std
    rolling_p70 = s.rolling(window=lookback, min_periods=lookback).apply(
        lambda w: np.nanpercentile(w, 70), raw=True
    )
    rolling_p60 = s.rolling(window=lookback, min_periods=lookback).apply(
        lambda w: np.nanpercentile(w, 60), raw=True
    )

    high_vol_sd_threshold = rolling_mean + 1.5 * rolling_sd
    high_sd_threshold = rolling_mean + rolling_sd

    classified_scores = []
    for x, mean_score, high_vol_percentile_threshold, high_percentile_threshold, sd_hi, sd_mid in zip(
        s, rolling_mean, rolling_p70, rolling_p60, high_vol_sd_threshold, high_sd_threshold
    ):
        if pd.isna(x) or pd.isna(mean_score):
            classified_scores.append("Low")
        elif (x > high_vol_percentile_threshold) and (x > sd_hi):
            classified_scores.append("Highly Volatile")
        elif (x > high_percentile_threshold) and (x > sd_mid):
            classified_scores.append("High")
        elif x > mean_score:
            classified_scores.append("Medium")
        else:
            classified_scores.append("Low")

    return classified_scores

# Calculates volatility threshold labels for each value vs the series average.
# Returns a list of strings: "Very High" / "High" / "Medium" / "Low"
def vol_threshs(indicator):
    medium_thresh = 0.75 # Change these based on analysis
    high_thresh = 1.25
    very_high_thresh = 2
    arr = pd.Series(indicator)
    avg_vol = np.nanmean(arr.values)

    volatility_periods = []
    for i in range(len(arr)):
        x = arr.iat[i]
        if np.isnan(x):
            volatility_periods.append("Low")
        elif (x < avg_vol * high_thresh) and (x > avg_vol * medium_thresh):
            volatility_periods.append("Medium")
        elif x > avg_vol * very_high_thresh:
            volatility_periods.append("Very High")
        elif x > avg_vol * high_thresh:
            volatility_periods.append("High")
        else:
            volatility_periods.append("Low")
    return volatility_periods

# Combines standardized ATR, VIX, and StdDev by averaging them (divide by 3)
def std_atr_stddev(standardised_atrs, standardised_stddev):
    a = pd.Series(standardised_atrs)
    b = pd.Series(standardised_stddev)
    combined_scores = (a + b) / 2.0

    if not any(isinstance(x, pd.Series) for x in (standardised_atrs, standardised_stddev)):
        return combined_scores.values
    return combined_scores

# Standard deviation of log returns over a rolling window (lookback)
# series is expected to be a DataFrame with a 'Close' column (like R's xts)
def stddev_rolling_window(series, lookback):
    close = pd.Series(series["Close"])
    close_safe = close.where(close > 0, np.nan)
    returns = np.log(close_safe).diff(1)
    rolling_stddev = returns.rolling(window=lookback).std()
    return rolling_stddev

# Neatly info out volatility analysis
def info_volatility_analysis(result, max_periods=10):
    info("\n\n\n📈 Volatility Diagnostic Summary")
    info(f"Asset: {result.get('asset')}")
    info(f"Start Date: {result.get('start_date')}")
    info(f"End Date: {result.get('end_date')}")
    info(f"Timeframe: {result.get('time_frame')}")
    info("-" * 40)

    # Overall classification
    series_vol = result.get("series_vol", "Unknown")
    info(f"Overall Series Volatility : {series_vol}")

    # Distribution of period classifications
    period_vol = result.get("period_vol", [])
    freq = Counter(period_vol)
    info("🧮 Period Volatility Distribution:")
    for label in ["Low", "Medium", "High", "Highly Volatile"]:
        count = freq.get(label, 0)
        info(f"  → {label:<18}: {count}")

    # Composite score snapshot
    combined_score = result.get("combined_score", [])
    if isinstance(combined_score, (list, pd.Series)) and len(combined_score) > 0:
        info("🔍 Composite Score Snapshot:")
        scores = pd.Series(combined_score).dropna()
        info(f"  Mean Score              : {scores.mean():.3f}")
        info(f"  Std Dev of Score        : {scores.std():.3f}")
        info(f"  Max Score               : {scores.max():.3f}")
        info(f"  Min Score               : {scores.min():.3f}")

    # Optional: info first few period classifications
    info("🕒 First Few Period Classifications:")
    for i, label in enumerate(period_vol[:max_periods]):
        info(f"  Period {i + 1:<2} → {label}")

    info("-" * 40)
