import os
import pandas as pd
import numpy as np
import src.trading.utils.constants as constants
import sys
from src.trading.data.data_analysis.analysis import rolling_analysis
from plotting.graphs import plot_volatiltiy_momentum_correlation_scatter
from src.trading.utils.logger import info, warning

def generate_and_plot_volatility_momentum_correlation(data_keys, data_values, data_map, pair, timeframe, start_date, end_date=None):
    for key in data_keys:
        series = data_map[pair]
        if end_date is None:
            info(f"Running rolling analysis for {pair} ({timeframe}) from {start_date.date()}")
        else:
            info(f"Running rolling analysis for {pair} ({timeframe}) from {start_date.date()} to {end_date.date()}")

        analysis = rolling_analysis(series, pair, timeframe, start_date)
        volatility_stats = analysis["volatility_stats"]

        combined_score = pad_to_length(volatility_stats["combined_score"], series.index)
        period_vol = pad_to_length(volatility_stats["period_vol"], series.index)
        series_vol = pad_to_length(volatility_stats["series_vol"], series.index)
        std_atrs = pad_to_length(volatility_stats["std_atrs"], series.index)
        std_std_dev = pad_to_length(volatility_stats["std_std_dev"], series.index)

        file_name = f"{pair}_{timeframe}"

        price_diffs = []
        combined_scores = []
        std_atrs_means = []
        std_atrs_stds = []
        std_atrs_maxes = []
        std_atrs_skews = []
        std_std_devs_means = []
        std_std_devs_stds = []
        std_std_devs_maxes = []
        std_std_devs_skews = []

        for (period_start, period_end) in analysis['momentum_periods']:
            info(f"Momentum period: {series.index[period_start]} to {series.index[period_end]}")

            price_diff = series['Close'].iloc[period_end] - series['Close'].iloc[period_start]
            price_diffs.append(price_diff)

            cs_slice = combined_score.iloc[period_start:period_end + 1]
            atrs_slice = std_atrs.iloc[period_start:period_end + 1]
            stddev_slice = std_std_dev.iloc[period_start:period_end + 1]
            pv_slice = period_vol.iloc[period_start:period_end + 1]
            sv_slice = series_vol.iloc[period_start:period_end + 1]

            combined_scores.append(cs_slice.mean())
            std_atrs_means.append(atrs_slice.mean())
            std_atrs_stds.append(atrs_slice.std())
            std_atrs_maxes.append(atrs_slice.max())
            std_atrs_skews.append(atrs_slice.skew())
            std_std_devs_means.append(stddev_slice.mean())
            std_std_devs_stds.append(stddev_slice.std())
            std_std_devs_maxes.append(stddev_slice.max())
            std_std_devs_skews.append(stddev_slice.skew())

            info(f"Start price: {series['Close'].iloc[period_start]}, End price: {series['Close'].iloc[period_end]}, Difference: {price_diff}")
            info(f"Combined Score: mean={cs_slice.mean():.4f}, std={cs_slice.std():.4f}")
            info(f"Standardized ATR: mean={atrs_slice.mean():.4f}, std={atrs_slice.std():.4f}, max={atrs_slice.max():.4f}, skew={atrs_slice.skew():.4f}")
            info(f"Standardized StdDev: mean={stddev_slice.mean():.4f}, std={stddev_slice.std():.4f}, max={stddev_slice.max():.4f}, skew={stddev_slice.skew():.4f}")
            info(f"Period Volatility label: {most_common_label(pv_slice)}, Series Volatility label: {most_common_label(sv_slice)}")

        df = pd.DataFrame({
            'price_diff': price_diffs,
            'combined_score': combined_scores,
            'std_atrs_mean': std_atrs_means,
            'std_atrs_std': std_atrs_stds,
            'std_atrs_max': std_atrs_maxes,
            'std_atrs_skew': std_atrs_skews,
            'std_std_dev_mean': std_std_devs_means,
            'std_std_dev_std': std_std_devs_stds,
            'std_std_dev_max': std_std_devs_maxes,
            'std_std_dev_skew': std_std_devs_skews
        })

        info(f"Generated DataFrame with {len(df)} momentum periods for {pair}")
        if len(df) >= 2:
            correlations = df.corr()['price_diff'].drop('price_diff')
            info("Correlation with price difference:")
            for feature, corr in correlations.sort_values(ascending=False).items():
                info(f"{feature}: {corr:.4f}")
            if end_date is not None:
                filepath = f"{constants.PRICE_VOLATILITY_CORR_DIR}/{start_date.date()}-{end_date.date()}/{timeframe}"
            else:
                filepath = f"{constants.PRICE_VOLATILITY_CORR_DIR}/{start_date.date()}/{timeframe}/"

            if not os.path.exists(filepath):
                os.makedirs(filepath)
            plot_volatiltiy_momentum_correlation_scatter(df, filepath, file_name)
            info(f"Saved scatter plots to {filepath}")
        else:
            warning(f"Not enough momentum periods to compute correlation for {pair}")


# Used to pad a dataframe, due to indicators using lookbacks
def pad_to_length(values, target_index):
    pad_len = len(target_index) - len(values)
    padded = [np.nan] * pad_len + list(values)
    return pd.Series(padded, index=target_index)

# Used in determining the most common volatility label over a slice
def most_common_label(series_slice):
    counts = series_slice.value_counts()
    return counts.idxmax() if not counts.empty else None