from datetime import datetime, timedelta
import os
import pandas as pd
import numpy as np
import trading.utils.constants as constants
from trading.utils.logger import info, warning, error

from trading.utils.config import load_config

CONFIGS_DIR = constants.CONFIGS_DIR
# Computes z-score standardization: (x - mean) / sd, ignoring NaNs
def zscore_standardisation(indicator_values):
    s = pd.Series(indicator_values)
    mean_val = np.nanmean(s.values)
    std_val = np.nanstd(s.values, ddof=1)  # sample std (R-style)

    z = (s - mean_val) / std_val
    return z if isinstance(indicator_values, pd.Series) else z.values

# Calculates the log returns of a series
def to_log_returns(series):
    series = pd.Series(series).dropna()
    log_returns = np.log(series).diff().dropna()
    return log_returns  # index is already aligned correctly

# # Function to return all CSV filenames in the directory
# def get_filenames(directory):
#     # List all files in the directory and filter for CSV files
#     info(directory)
#     return [f for f in os.listdir(directory) if f.endswith('.csv')]

# Reads a CSV and converts the 'Time' column to datetime, removing any "+00:00" timezone suffix.
def preprocess_csv(filename):
    data = pd.read_csv(filename)
    info(f"Columns in {filename}: {data.columns.tolist()}")
    if data.empty:
        warning(f"The DataFrame at {filename} is empty", __file__)
        return None

    data["Time"] = pd.to_datetime(data["Time"], utc=True).dt.tz_localize(None)

    # Set Time as DatetimeIndex
    data.set_index("Time", inplace=True)

    info(f"CSV loaded and preprocessed: {filename}")
    return data


# # Function to read and convert a CSV file to a DataFrame with a datetime index
# def read_file(filename):
#     data = preprocess_csv(filename)
#     return data.set_index('Time')

# # Function to return a list of DataFrames in OHLCV format
# def get_data(directory):
#     # Construct the full path to the directory
#     directory = os.path.join("DATA", directory)
#     # Get all filenames in the directory
#     filenames = get_filenames(directory)
#
#     info(f"Read {len(filenames)} series from {directory}")
#     # Apply read_file to each filename
#     return [read_file(os.path.join(directory, fname)) for fname in filenames]

# Returns an array of all forex data frames on a given date for a given time frame
# There are two possible usages of this function, depending on the parameterisation.
# If the function is passed parameters, it will use these as the time frames, otherwise, it will use the config file information
def get_forex_data(
    config_file=None,
    pair=None,
    year=None,
    timeframe=None,
    start_date=None,
    end_date=None,
):
    try:
        info(f"Current file is {__file__}")

        # --- Load config if provided ---
        if config_file:
            config = load_config(os.path.join(CONFIGS_DIR, config_file))
            info(f"Asset Config loaded: {config}")

            pair = config["pair"]
            year = config["year"]
            timeframe = config["timeframe"]
            start_date = config["start_date"]
            end_date = config["end_date"]

        start = datetime.strptime(f"{year}-{start_date}", "%Y-%m-%d")
        end = datetime.strptime(f"{year}-{end_date}", "%Y-%m-%d")

        dfs = []

        current = start
        while current <= end:
            date_str = current.strftime("%m-%d")

            file = os.path.join(
                constants.OANDA_FOREX_DATA_DIR,
                pair,
                str(year),
                timeframe,
                date_str,
                f"{pair}.csv",
            )

            info(f"Reading {file}")

            df = preprocess_csv(file)
            if df is not None:
                dfs.append(df)

            current += timedelta(days=1)

        if not dfs:
            error(f"No data files loaded", __file__)
            raise ValueError("No data files loaded.")

        combined = pd.concat(dfs)
        combined.sort_index(inplace=True)  # sort by DatetimeIndex

        info(f"Combined dataframe length = {len(combined)}")
        return combined

    except Exception as e:
        error(f"Issue with getting forex data: {e}", __file__)
        raise


# Creates a dictionary with asset information, such as time frame, pair, date information and the actual data itself
def create_asset_dictonary(config_file, data):
    info(f"Current file is {__file__}")
    config = load_config(os.path.join(CONFIGS_DIR, config_file))
    asset_dict = {"asset": config["pair"],
            "year": config["year"],
            "timeframe": config["timeframe"],
            "start_date": config["start_date"],
            "end_date": config["end_date"],
            "data": data}

    info(f"Created asset dictonary: {asset_dict}")
    return asset_dict
