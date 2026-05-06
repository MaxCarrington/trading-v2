import pandas as pd

#Calculates the Average True Range (ATR) using Wilder's smoothing method.
#This is a fully optimized, vectorized implementation.
#
#ATR_t = (ATR_{t-1} * (n - 1) + TR_t) / n
#where:
#  TR_t = max(High - Low, abs(High - PrevClose), abs(Low - PrevClose))
def calculate_rolling_atr(series, lookback=14):
    # --- Calculate True Range (vectorized) ---
    high_low = series["High"] - series["Low"]
    high_prev_close = (series["High"] - series["Close"].shift(1)).abs()
    low_prev_close = (series["Low"] - series["Close"].shift(1)).abs()
    true_range = pd.concat([high_low, high_prev_close, low_prev_close], axis=1).max(axis=1)

    # --- Initialize ATR Series ---
    atr = pd.Series(index=series.index, dtype=float)

    # --- First ATR value: simple average of first N TR values ---
    atr.iloc[lookback - 1] = true_range.iloc[:lookback].mean()

    # --- Wilder’s recursive smoothing for all later values ---
    for i in range(lookback, len(series)):
        atr.iloc[i] = ((atr.iloc[i - 1] * (lookback - 1)) + true_range.iloc[i]) / lookback

    # Optional: forward fill first (lookback - 1) values for continuity
    atr.iloc[:lookback - 1] = atr.iloc[lookback - 1]

    return atr
