import pandas as pd
import numpy as np
import nolds
from hurst import compute_Hc

# Calculates the Hurst exponent
# The Hurst exponent measures the degree of stationarity or trend of a time
# series. For a price series exhibiting a geometric random walk, H = 0.5, but
# for a mean reverting series, H < 0.5, and for a trending series, H > 0.5. As H
# decreases toward zero, the price series is more mean reverting and as H
# increases toward 1 the price series is increasingly trending.
def calculate_hurst_exponent(series):
    series = pd.Series(series)
    clean_series = series[series > 0].dropna()  # avoid log(0) or negatives
    log_returns = np.log(clean_series).diff().dropna()

    if len(clean_series) < 100:
        print("Skipping Hurst calculation: series too short (<100)")
        h = np.nan
    else:
        try:
            h, _, _ = compute_Hc(clean_series, kind='price', simplified=True)
        except Exception as e:
            print(f"Error computing Hurst exponent: {e}")
            h = np.nan

    if np.isnan(h):
        try:
            h = nolds.hurst_rs(log_returns, fit='poly')  # 'ransac' not supported here
        except ImportError:
            print("nolds not installed, cannot compute fallback Hurst exponent.")
            return {'hurst': None, 'classification': 'undefined'}
        except Exception as e:
            print(f"Fallback Hurst RS failed: {e}")
            return {'hurst': None, 'classification': 'undefined'}

    if h < 0.45:
        classification = "mean_reverting"
    elif 0.45 <= h < 0.50:
        classification = "random_walk"
    elif h > 0.50:
        classification = "trending"
    else:
        classification = "undefined"

    return {'hurst': h, 'classification': classification}

