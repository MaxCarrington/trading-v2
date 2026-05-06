import os
from datetime import datetime
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

import trading.utils.constants as constants
from trading.utils.config import get_initial_capital

# Calculates the maximum drawdown from a cumulative PnL series.
def max_drawdown(cumPnL):
    return (cumPnL.cummax() - cumPnL).max()

# Returns the timestamp where the maximum drawdown ends.
def max_drawdown_end(cumPnL):
    return cumPnL.index[(cumPnL.cummax() - cumPnL).argmax()]

# Returns the timestamp where the maximum drawdown begins.
def max_drawdown_start(cumPnL):
    end_idx = (cumPnL.cummax() - cumPnL).argmax()
    start_idx = cumPnL[:end_idx + 1].argmax()
    return cumPnL.index[start_idx]

# Computes the PD ratio (final PnL divided by max drawdown) with debug output.
def pd_ratio(series):
    mdd = (series.cummax() - series).max()
    final = series.iloc[-1]

    print("---- PD Ratio Debug ----")
    print("Final PnL:", final)
    print("Max Drawdown:", mdd)
    print("Series Head:\n", series.head())
    print("Series Tail:\n", series.tail())
    print("------------------------")

    if mdd == 0:
        return float('nan') if final > 0 else round(final, 2)
    return round(final / mdd, 2)

# Returns a formatted string showing the PD ratio calculation.
def pd_ratio_string(series):
    mdd = (series.cummax() - series).max()
    final = round(series.iloc[-1], 2)
    if mdd == 0:
        return f"PD ratio = {final} / 0 = NaN"
    ratio = round(final / mdd, 2)
    return f"PD ratio = {final} / {round(mdd, 2)} = {ratio}"

# Aggregates daily and cumulative PnL across multiple strategies.
def aggregate_pnl(pnl_list):
    base_index = pnl_list[0].index
    daily_pnl = pd.Series(0.0, index=base_index)

    for df in pnl_list:
        daily_pnl += df["DailyPnL"]

    cum_pnl = daily_pnl.cumsum()
    return pd.DataFrame({
        "DailyPnL": daily_pnl,
        "CumPnL": cum_pnl
    })

# Plots portfolio and strategy performance with PD ratios and drawdown shading.
def plot_strategy_results(data_list, results, title_string="test", save=False):
    starting_capital = get_initial_capital()
    nseries = len(data_list)

    pfolio_pnl = aggregate_pnl(results["pnlList"])
    pfolio_networth = results["netWorthList"]

    # Extract CumPnL series
    cumpnl_list = [df["CumPnL"] for df in results["pnlList"]]
    all_series = pd.concat(cumpnl_list, axis=1)
    all_series.columns = [f"{name}:" for name in data_list]

    # Compute PD ratios
    pdr_list = [pd_ratio(df["CumPnL"]) for df in results["pnlList"]]


    # Combine net worth and individual series
    toplot = pd.concat([pfolio_networth, all_series], axis=1)
    toplot.columns = [f"Active on {results['k']}% of days;"] + list(all_series.columns)

    # Adjust first column for PD ratio
    pd_ratio_lists = toplot.copy()
    pd_ratio_lists.iloc[:, 0] -= starting_capital

    # Update column names with PD ratio strings
    net_pnl = toplot.iloc[:, 0] - starting_capital

    print("---- Portfolio Net Worth Debug ----")
    print("Net Worth Head:\n", toplot.iloc[:, 0].head())
    print("Net Worth Tail:\n", toplot.iloc[:, 0].tail())
    print("Net PnL Head:\n", net_pnl.head())
    print("Net PnL Tail:\n", net_pnl.tail())
    print("PD Ratio:", pd_ratio(net_pnl))
    print("------------------------")

    toplot.columns = [
        f"{name} {pd_ratio_string(net_pnl if i == 0 else pd_ratio_lists[name])}"
        for i, name in enumerate(toplot.columns)
    ]

    # Drawdown markers
    st = max_drawdown_start(pfolio_pnl["CumPnL"])
    en = max_drawdown_end(pfolio_pnl["CumPnL"])

    # Plot aggregate performance
    fig, axes = plt.subplots(nrows=2, figsize=(14, 10), gridspec_kw={"height_ratios": [0.75, 2]})

    toplot.iloc[:, 0].plot(ax=axes[0], title=toplot.columns[0])
    axes[0].axhline(starting_capital, color="red", linestyle="--")
    axes[0].axvspan(st, en, color="blue", alpha=0.2)
    axes[0].set_ylabel("")
    axes[0].set_xlabel("")
    axes[0].set_title(toplot.columns[0])

    # Plot individual series
    for i, col in enumerate(toplot.columns[1:]):
        sns.lineplot(data=toplot[col], ax=axes[1], label=col)

    axes[1].axhline(0, color="red", linestyle="--")
    axes[1].set_ylabel("")
    axes[1].set_xlabel("")
    axes[1].legend(loc="upper left", bbox_to_anchor=(1, 1))

    if title_string:
        fig.suptitle(title_string, fontsize=16, fontweight="bold")

    plt.tight_layout()
    plt.show(block=False)

    dir_to_save = constants.RESULTS_FIGURES_DIR
    filename = datetime.now().strftime("%Y%m%d-%H%M%S") + title_string + ".png"

    if save:
        save_plot(fig, dir_to_save, filename)

    return {
        "pfoliosPnL": pfolio_pnl,
        "fitInd": max(pdr_list),
        "fitAgg": pd_ratio(pfolio_pnl["CumPnL"])
    }

# Saves a figure with a specific file name to a specific directory
def save_plot(fig, save_dir, file_name, dpi=300):
    print(file_name)
    # Ensure directory exists
    if not os.path.isdir(save_dir):
        os.makedirs(save_dir, exist_ok=True)

    # Construct full file path
    file_path = os.path.join(save_dir, file_name)

    # Save the figure
    fig.savefig(file_path, dpi=dpi, bbox_inches='tight')
    print(f"Plot saved to: {file_path}")