import os
import pandas as pd
import mplfinance as mpf

import matplotlib.pyplot as plt
import src.trading.utils.constants as constants
from src.trading.indicators.average_true_range import calculate_rolling_atr
from src.trading.data.data_analysis.volatility_analysis import classify_volatility

_REGIME_COLORS = {
    "Low": "green",
    "Medium": "gold",
    "High": "red",
    "Highly Volatile": "darkred",
}

# Plots a candle stick chart for a time series at a particular time interval on a certain date
def plot_candlestick_chart(series, asset_name, time_interval, date, data_path=None):
    if data_path is None:
        data = series
    else:
        try:
            data = pd.read_csv(data_path, index_col=0, parse_dates=True)
        except Exception as e:
            print(f"Error loading data: {e}")
            return

    # Ensure the "charts" folder exists in the current directory
    folder = os.path.join(constants.CANDLES_DIR, asset_name, time_interval, date)
    if not os.path.exists(folder):
        os.makedirs(folder)
    # Create the filename based on the series and time parameters, e.g., "AUD_USD_M5_2024-11-11.png"
    filename = f"{asset_name}_{time_interval}_{date}.png"
    filepath = os.path.join(folder, filename)

    # Make the chart bigger + increase DPI (resolution)
    fig, axlist = mpf.plot(
        data,
        type='candle',
        style='charles',
        title=f"{asset_name} {time_interval} Candlestick Chart ({date})",
        figsize=(14, 8),  # increase chart size
        returnfig=True
    )

    # Save the figure with high resolution
    fig.savefig(filepath, dpi=300, bbox_inches="tight")  # 300 DPI is print-quality
    fig.show()

    print(f"Chart saved as: {filepath}")

# Plots a candle stick chart with volatility plots for a time series at a particular time interval on a certain date
def plot_candles_with_volatility_from_dict(series, asset_name, time_interval, date, vol_dict, lookback=12, atr_mult=2.0, data_path=None):
    # --- load data ---
    data = series if data_path is None else pd.read_csv(data_path, index_col=0, parse_dates=True)

    # --- output path ---
    folder = os.path.join(constants.CANDLES_WITH_VOLATILITY_DIR, asset_name, time_interval, date)
    os.makedirs(folder, exist_ok=True)
    filepath = os.path.join(folder, f"{asset_name}_{time_interval}_{date}.png")

    # --- standardized components ---
    std_atrs = pd.Series(vol_dict.get("std_atrs")).reindex(data.index)
    std_std  = pd.Series(vol_dict.get("std_std_dev")).reindex(data.index)

    combined = vol_dict.get("combined_score")
    if combined is None:
        combined = (std_atrs + std_std) / 2.0
    combined = pd.Series(combined).reindex(data.index)

    # --- price panel: Keltner-style bands from ATR ---
    atr   = calculate_rolling_atr(data, lookback).reindex(data.index)
    mid   = data["Close"].ewm(span=lookback, adjust=False).mean()
    upper = mid + atr_mult * atr
    lower = mid - atr_mult * atr

    # --- addplots ---
    apds = [
        mpf.make_addplot(mid,   panel=0, width=1,   alpha=0.9),
        mpf.make_addplot(upper, panel=0, width=0.8, alpha=0.8),
        mpf.make_addplot(lower, panel=0, width=0.8, alpha=0.8),
    ]

    # only create a volatility panel if there’s data
    has_vol_line = bool(pd.Series(combined).notna().any())
    if has_vol_line:
        masked_combined = combined.copy()
        masked_combined[masked_combined.isna()] = 0.0  # or np.nan if you want gaps
        apds.append(mpf.make_addplot(masked_combined, panel=1, width=1.2))

    # panels: price (+ optional volatility)
    title = f"{asset_name} {time_interval} ({date})"

    fig, axlist = mpf.plot(
    data,
    type = 'candle',
    style = 'charles',
    title = title,
    figsize = (16, 8),  # a bit wider than before
    addplot = apds,
    panel_ratios = (3, 1),  # price + volatility panels (no volume)
    returnfig = True
    )

    fig.subplots_adjust(left=0.30)  # ~30% of the figure width becomes sidebar

    ax_text = fig.add_axes([0.04, 0.12, 0.22, 0.76])
    ax_text.axis('off')

    # 4) Sidebar content
    explainer = (
    f"WHAT THIS SHOWS\n"
    f"• Candles: `{time_interval} price for {asset_name} ({date}).\n"
    f"• Mid (blue): EMA({lookback}).\n"
    f"• ATR envelopes (orange/green): EMA ± {atr_mult}×ATR({lookback}).\n"
    f"  Wider bands → higher realized range/volatility.\n"
    f"• Volatility score (lower panel): z-score average of\n"
    f"  standardized ATR and StdDev.\n\n"
    )
    ax_text.text(0.0, 1.0, explainer, va='top', ha='left', fontsize=10, linespacing=1.25)

    # 5) Save
    fig.savefig(filepath, dpi=300, bbox_inches="tight")

# Plots a candlestick chart with a volatility panel underneath
def plot_candles_with_vol_panel(series, asset_name, time_interval, date, vol_dict, lookback=20, atr_mult=2.0, data_path=None):
    # --- load data ---
    data = series if data_path is None else pd.read_csv(data_path, index_col=0, parse_dates=True)

    # --- output path ---
    folder = os.path.join(constants.CANDLES_WITH_VOLATILITY_DIR, asset_name, time_interval, date)
    os.makedirs(folder, exist_ok=True)
    filepath = os.path.join(folder, f"{asset_name}_{time_interval}_{date}.png")

    # --- standardized components ---
    std_atrs = pd.Series(vol_dict.get("std_atrs")).reindex(data.index)
    std_std = pd.Series(vol_dict.get("std_std_dev")).reindex(data.index)

    combined = vol_dict.get("combined_score")
    if combined is None:
        combined = (std_atrs + std_std) / 2.0
    combined = pd.Series(combined).reindex(data.index)

    # --- classify volatility ---
    valid_idx = combined.dropna().index
    vol_labels = pd.Series(index=combined.index, dtype=object)

    if len(valid_idx) > 0:
        classified = classify_volatility(combined.loc[valid_idx])
        classified = classified[:len(valid_idx)]
        vol_labels.loc[valid_idx] = classified

    # --- price panel: Keltner-style bands from ATR ---
    atr = calculate_rolling_atr(data, lookback).reindex(data.index)
    mid = data["Close"].ewm(span=lookback, adjust=False).mean()
    upper = mid + atr_mult * atr
    lower = mid - atr_mult * atr

    # --- addplots ---
    apds = [
        mpf.make_addplot(mid, panel=0, width=1, alpha=0.9),
        mpf.make_addplot(upper, panel=0, width=0.8, alpha=0.8),
        mpf.make_addplot(lower, panel=0, width=0.8, alpha=0.8),
    ]

    # --- volatility panel ---
    if combined.notna().any():
        apds.append(mpf.make_addplot(combined, panel=1, width=1.2))
    else:
        apds.append(mpf.make_addplot(pd.Series(0.0, index=data.index), panel=1, width=0))

    # --- test panel: force creation with dummy series BEFORE plotting ---
    dummy_series = pd.Series(0.0, index=data.index)
    apds.append(mpf.make_addplot(dummy_series, panel=2, width=0))  # invisible line

    # --- plot ---
    title = f"{asset_name} {time_interval} ({date})"
    fig, axlist = mpf.plot(
        data,
        type='candle',
        style='charles',
        title=title,
        figsize=(16, 8),
        addplot=apds,
        panel_ratios=(3, 1, 1),
        volume=False,
        returnfig=True
    )
    # --- shade test panel using regime colours and float axis values ---
    test_ax = axlist[2]
    colors_by_label = _REGIME_COLORS
    timestamps = combined.dropna().index.to_list()
    n_blocks = len(timestamps) - 1

    # Get axis limits in float format
    xmin, xmax = test_ax.get_xlim()
    print(n_blocks - lookback)
    print(len(combined))
    block_width = (xmax - xmin) / n_blocks

    start_index = lookback  # skip first N blocks
    for i in range(start_index, n_blocks):
        x0 = xmin + i * block_width
        x1 = x0 + block_width
        label = vol_labels.loc[timestamps[i]]
        color = colors_by_label.get(label, "gray")
        test_ax.axvspan(x0, x1, color=color, alpha=0.3, zorder=0)

    # --- sidebar ---
    fig.subplots_adjust(left=0.30)
    ax_text = fig.add_axes([0.04, 0.12, 0.22, 0.76])
    ax_text.axis('off')

    explainer = (
        f"WHAT THIS SHOWS\n"
        f"• Candles: {time_interval} price for {asset_name} ({date}).\n"
        f"• Mid (blue): EMA({lookback}).\n"
        f"• ATR envelopes (orange): EMA ± {atr_mult}×ATR({lookback}).\n"
        f"  Wider bands → higher realized volatility.\n"
        f"• Lower panel: z-score average of standardized ATR & StdDev.\n"
        f"  Background tinted by volatility regime."
    )
    ax_text.text(0.0, 1.0, explainer, va='top', ha='left', fontsize=10, linespacing=1.25)

    # --- save ---
    fig.savefig(filepath, dpi=300)
    print(f"Chart saved as: {filepath}")

    plt.show()

# Plots a candlestick chart with periods of mean reversion and momentum, generated by analysis
def plot_candlestick_chart_with_analysis_periods(series, asset_name, time_interval, date, periods, data_path=None):

    data = series if data_path is None else pd.read_csv(data_path, index_col=0, parse_dates=True)
    data.dropna(subset=['Open', 'High', 'Low', 'Close'], inplace=True)

    folder = os.path.join(constants.CANDLES_DIR, asset_name, time_interval, date,  "WITH_MEAN_REV_MOMENTUM_PERIODS")
    os.makedirs(folder, exist_ok=True)
    filename = f"{asset_name}_{time_interval}_{date}.png"
    filepath = os.path.join(folder, filename)

    # Create regime series
    momentum_series = pd.Series(0.0, index=data.index)
    mean_reversion_series = pd.Series(0.0, index=data.index)

    for start_idx, end_idx in periods['momentum_periods']:
        if 0 <= start_idx < len(data) and 0 <= end_idx < len(data):
            momentum_series.iloc[start_idx:end_idx+1] = 1.0

    for start_idx, end_idx in periods['mean_reversion_periods']:
        if 0 <= start_idx < len(data) and 0 <= end_idx < len(data):
            mean_reversion_series.iloc[start_idx:end_idx+1] = -1.0

    # Create addplots
    apds = [
        mpf.make_addplot(momentum_series, panel=1, type='bar', color='green'),
        mpf.make_addplot(mean_reversion_series, panel=1, type='bar', color='blue')
    ]

    # Plot everything
    fig, axlist = mpf.plot(
        data,
        type='candle',
        style='charles',
        title=f"{asset_name} {time_interval} Candlestick Chart with Regime Timeline ({date})",
        figsize=(14, 8),
        addplot=apds,
        panel_ratios=(4, 1),
        returnfig=True
    )

    fig.savefig(filepath, dpi=300)
    print(f"Chart saved as: {filepath}")
    import matplotlib.pyplot as plt
    plt.show()



