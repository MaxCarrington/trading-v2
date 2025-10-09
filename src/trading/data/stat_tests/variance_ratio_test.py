import pandas as pd
from arch.unitroot import VarianceRatio
from src.trading.utils.data_manipulation import to_log_returns
# Performs a Variance Ratio Test
# Used to test the random walk hypothesis in a time series. The null hypothesis
# is that the series is a random walk (in this case, the variance ratio will be
# 1). However, if there is a notable deviation from 1 the time series may be
# mean reverting or trending. Performs a variance ratio test on a given time
# series and returns the variance
def perform_variance_ratio_test(series, lags=[2, 3, 5, 10], alpha=0.05, deviation_threshold=0.05):
    series = to_log_returns(pd.Series(series).dropna())
    for k in lags:
        try:
            vr_test = VarianceRatio(series, lags=k)
            stat = vr_test.stat
            pval = vr_test.pvalue
            vr_value = vr_test.vr

            if pval < alpha and abs(vr_value - 1) >= deviation_threshold:
                return {
                    'Significant': True,
                    'Lag': k,
                    'Stats': {
                        'stat': stat,
                        'p_value': pval,
                        'vr': vr_value
                    }
                }
        except Exception as e:
            print(f"VR test failed for lag {k}: {e}")
            continue

    return {'Significant': False, 'Lag': None, 'Stats': None}
