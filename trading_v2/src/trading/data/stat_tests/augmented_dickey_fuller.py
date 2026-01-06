from statsmodels.tsa.stattools import adfuller
from src.trading.utils.data_manipulation import to_log_returns
# Performs an Augmented Dickey fuller test
# Determines if a time series is stationary by testing for a unit root (a null
# hypothesis). If there is a unit root, then the time series may be
# non-stationary. Alternatively if there is no unit root, this is indicative of
# stationarity.
from statsmodels.tsa.stattools import adfuller

percentage_map = {
    0.01: '1%',
    0.05: '5%',
    0.10: '10%',
}

#Performs Augmented Dickey-Fuller test and checks stationarity against a specified significance level.
def perform_adf_test(series, percentage_level=0.05, print_output=False):
    clean_series = to_log_returns(series.dropna())
    result = adfuller(clean_series, autolag='AIC')

    if percentage_level not in percentage_map:
        raise ValueError(f"Unsupported significance level: {percentage_level}")

    crit_key = percentage_map[percentage_level]
    critical_value = result[4][crit_key]
    adf_statistic = result[0]
    p_value = result[1]

    is_stationary = adf_statistic < critical_value and p_value < percentage_level

    if print_output:
        print(f"{'Stationary' if is_stationary else 'Non-stationary'} at {crit_key} level")

    return {
        'adf_statistic': adf_statistic,
        'p_value': result[1],
        'used_lag': result[2],
        'n_obs': result[3],
        'critical_values': result[4],
        'ic_best': result[5],
        'is_stationary': is_stationary
    }
