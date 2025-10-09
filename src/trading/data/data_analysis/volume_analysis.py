import pandas as pd
import numpy as np
import ta
import warnings
sssss
from ta.trend import ema_indicator
from scipy.stats import pearsonr

from src.trading.utils.data_manipulation import zscore_standardisation

warnings.filterwarnings("ignore", category=RuntimeWarning, message="Degrees of freedom <= 0 for slice")


# Analyses periods of high trading volume and liquidity
def combined_liquidity_analysis(series, vol_lookback=20, liquidity_thresh=0.6, window_size=10):
    # Identify high volume periods
    high_volume_periods = high_liquidity_periods(series, vol_lookback, liquidity_thresh)

    # Filter the series to only those periods
    high_vol_series = series.loc[high_volume_periods]

    # Estimate liquidity indicators on the high volume subset
    liquidity_indicators = estimate_liquidity(high_vol_series, window_size)

    # Select final periods where liquidity is high
    high_liquidity_flags = liquidity_indicators['high_liquidity']
    if isinstance(high_liquidity_flags, pd.Series):
        final_selection = high_liquidity_flags[high_liquidity_flags == 1].index
    else:
        final_selection = high_volume_periods if high_liquidity_flags == 1 else pd.Index([])

    vwap_series = liquidity_indicators['vwap']
    vwap_at_liquidity = vwap_series.loc[final_selection]
    reliability_at_liquidity = liquidity_indicators['reliability'].loc[final_selection]

    # Generate scores and regime tags for each windowed period
    scores = [score_period(series, i, window_size) for i in range(window_size, len(series))]
    regimes = [tag_regime(s['liquidity'], s['momentum']) for s in scores]

    # Attach timestamps to scores
    score_df = pd.DataFrame(scores, index=series.index[window_size:])
    score_df['regime'] = regimes

    return {
        'high_volume_periods': high_volume_periods,
        'final_selection': final_selection,
        'liquidity_indicators': liquidity_indicators,
        'total_periods': len(series['Volume']) - (vol_lookback - 1),
        'lookback': vol_lookback,
        'liquidity_thresh': liquidity_thresh,
        'window_size': window_size,
        'vwap-at_liquidity': vwap_at_liquidity,
        'regime_scores': score_df,
        'reliability_at_liquidity': reliability_at_liquidity,
    }

def score_period(series, idx, window):
    sub = series.iloc[idx-window:idx]
    liq = estimate_liquidity(sub, window)['high_liquidity'].iloc[-1]
    mom = vol_inc_with_trend(sub, window)['correlation']
    return {'liquidity': liq, 'momentum': mom}

def tag_regime(liquidity, momentum, threshold=0.5):
    if liquidity and momentum > threshold:
        return 'Breakout'
    elif liquidity:
        return 'Liquidity'
    elif momentum > threshold:
        return 'Momentum'
    else:
        return 'Neutral'

# Determines if volume spikes are correlated with mean reversion
def vol_mr_correlation(series, window_size, threshold):
    cor_score_value = 1
    no_cor_score_value = 0

    # Calculate EMA of trading volume
    ema_volume = ema_indicator(close=series['Volume'], window=window_size).dropna()

    # Determine threshold for volume spikes
    vol_thresh = ema_volume.quantile(threshold)

    # Identify periods of volume spikes
    vol_spikes = series['Volume'] > vol_thresh
    vol_spike_periods = np.where(vol_spikes)[0]

    scores = []

    for i in vol_spike_periods:
        if i != 0:
            start_period = series.index[i]
            mean_revert_price = calculate_previous_mean_ema(series['Close'], window_size, start_period)

            end_index = min(i + window_size, len(series['Close']))
            last_price = series['Close'].iloc[i:end_index].iloc[-1]

            score = score_spike(last_price, mean_revert_price, threshold, cor_score_value, no_cor_score_value)
            scores.append(score)

    ranking_score = np.mean(scores) if scores else 0
    return

# Calculates an EMA of prices before a given period for mean reversion reference.
def calculate_previous_mean_ema(series, window_size, start_period_date):
    relevant_series = series[series.index < start_period_date]

    if len(relevant_series) >= window_size:
        ema_values = ema_indicator(relevant_series, window=window_size)
        mean_revert_price = ema_values.dropna().iloc[-1]
    else:
        mean_revert_price = relevant_series.mean(skipna=True)

    return mean_revert_price

# Determines if a price spike is aligned with mean reverting criteria
def score_spike(last_price, mean_revert_price, threshold, cor_score_value, no_cor_score_value):
    if abs(last_price - mean_revert_price) < threshold:
        return cor_score_value
    else:
        return no_cor_score_value

# For momentum, analyze increasing volume trends alongside price increases
def vol_inc_with_trend(series, window_size):
    # EMA of volume using ta
    ewma_vol = ema_indicator(close=series['Volume'], window=window_size)

    # Detect price increases and apply EMA using ta
    price_increases = detect_price_increase(series['Close'])
    ewma_price_inc = ema_indicator(close=price_increases, window=window_size)

    # Align lengths
    min_length = min(len(ewma_vol), len(ewma_price_inc))
    ewma_vol = ewma_vol[-min_length:]
    ewma_price_inc = ewma_price_inc[-min_length:]

    norm_prices = zscore_standardisation(ewma_price_inc)
    norm_vol = zscore_standardisation(ewma_vol)

    # Drop NaNs before correlation
    valid = norm_prices.notna() & norm_vol.notna()
    valid = norm_prices.notna() & norm_vol.notna()
    if valid.sum() < 2:
        correlation, p_value = np.nan, np.nan
    else:
        correlation, p_value = pearsonr(norm_vol[valid], norm_prices[valid])

    return {
        'correlation': correlation,
        'p_value': p_value
    }

# Identifies periods where prices increase compared to the previous period
def detect_price_increase(prices):
    price_changes = prices.diff()
    price_increases = (price_changes > 0).astype(int)
    return price_increases

# Estimates liquidity within high volume periods using volatility and VWAP
def estimate_liquidity(series, window_size=10):
    if len(series.dropna()) < window_size:
        return {
            'high_liquidity': pd.Series(index=series.index, data=np.nan),
            'vwap': pd.Series(index=series.index, data=np.nan),
            'reliability': pd.Series(index=series.index, data=np.nan)
        }

    volatility = (series['High'] - series['Low']) / series['Low']
    vwap = (series['High'] + series['Low'] + series['Close']) / 3

    avg_volume = series['Volume'].rolling(window=window_size).mean()
    avg_volatility = volatility.rolling(window=window_size).mean()

    high_liquidity_flags = ((volatility < avg_volatility) & (series['Volume'] > avg_volume)).astype(int)
    reliability_score = ((series['Volume'] / avg_volume) * (avg_volatility / volatility)).replace([np.inf, -np.inf], np.nan)

    return {
        'high_liquidity': high_liquidity_flags,
        'vwap': vwap,
        'reliability': reliability_score
    }


# Combines normalised price and volume into a score
def standard_price_n_vol(norm_prices, norm_volume):
    return (norm_prices + norm_volume) / 2

# Use the volume to determine if we are currently in a high liquidity periods
def is_high_liquidity(volume, lookback, threshold):
    rolling_median = volume.rolling(window=lookback).median()
    current_volume = volume.iloc[-1]
    return current_volume > (threshold * rolling_median.iloc[-1])

# Identifies periods where trading volume is higher than a rolling average threshold
def high_liquidity_periods(series, vol_lookback, threshold):
    # Calculate SMA of volume using ta
    sma_volume = ta.trend.sma_indicator(series['Volume'], window=vol_lookback)

    # Drop NaNs for quantile calculation
    valid_sma = sma_volume.dropna()
    high_volume_threshold = valid_sma.quantile(threshold)

    # Identify periods where SMA volume exceeds threshold
    high_volume_periods = sma_volume[sma_volume > high_volume_threshold].index

    return high_volume_periods

# Print function to neatly display results
def print_liquidity_analysis(result):
    print("\n💧 Liquidity Diagnostic Summary")
    print("-" * 40)
    print(f"Lookback Window          : {result.get('lookback')}")
    print(f"Liquidity Threshold      : {result.get('liquidity_thresh')}")
    print(f"Volatility Window Size   : {result.get('window_size')}")
    print(f"Total Periods Analyzed   : {result.get('total_periods')}")
    print(f"High Volume Periods      : {len(result.get('high_volume_periods', []))}")

    final_selection = result.get('final_selection', [])
    print(f"High Liquidity Selections: {len(final_selection)}")
    print("-" * 40)

    # 🕒 Print all high liquidity timestamps
    if len(final_selection) > 0:
        print("🕒 All High Liquidity Timestamps")
        for ts in final_selection:
            print(f"  → {ts}")
        print("-" * 40)
    else:
        print("⚠️ No high liquidity periods detected.")
        print("-" * 40)

    # 💰 VWAP values at high liquidity periods
    vwap_liq = result.get('vwap-at_liquidity')
    if isinstance(vwap_liq, pd.Series) and not vwap_liq.empty:
        print("💰 VWAP at High Liquidity Periods:")
        print(vwap_liq)
        print("-" * 40)

    # 📊 Reliability scores at high liquidity periods
    reliability = result.get('reliability_at_liquidity')
    if isinstance(reliability, pd.Series) and not reliability.empty:
        print("📊 Reliability Scores at High Liquidity Periods:")
        print(reliability)
        print("-" * 40)

    # 🧭 Regime tags from scored windows
    regime_scores = result.get('regime_scores')
    if isinstance(regime_scores, pd.DataFrame) and not regime_scores.empty:
        print("🧭 Regime Tags (first 10 scored periods):")
        print(regime_scores[['regime']].head(10))
        print("-" * 40)


