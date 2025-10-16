import os
import pandas as pd
import numpy as np
from pathlib import Path
import pathlib
import src.trading.utils.constants as constants
from src.trading.utils.config import get_config_file_default, load_config

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

# Function to return all CSV filenames in the directory
def get_filenames(directory):
    # List all files in the directory and filter for CSV files
    print(directory)
    return [f for f in os.listdir(directory) if f.endswith('.csv')]

def preprocess_csv(filename):
    data = pd.read_csv(filename, header=0, sep=',')
    # Remove the timezone offset using a raw string and specifying regex=True
    data['Time'] = data['Time'].str.replace(r"\+00:00", "", regex=True)
    # Now convert to datetime using the specified format
    data['Time'] = pd.to_datetime(data['Time'], format='%Y-%m-%d %H:%M:%S')
    return data

# Function to read and convert a CSV file to a DataFrame with a datetime index
def read_file(filename):
    data = preprocess_csv(filename)
    return data.set_index('Time')

# Function to return a list of DataFrames in OHLCV format
def get_data(directory):
    # Construct the full path to the directory
    directory = os.path.join("DATA", directory)
    # Get all filenames in the directory
    filenames = get_filenames(directory)
    print(f"Read {len(filenames)} series from {directory}")
    # Apply read_file to each filename
    return [read_file(os.path.join(directory, fname)) for fname in filenames]

# Returns an array of all forex data frames on a given date for a given time frame. Currently only uses the default config file
def get_all_forex_data_on_date():
    config = load_config(get_config_file_default())
    data = get_data_for_timeframe_date(constants.OANDA_DATA_DIR, config["timeframe"], config["date"])
    return data

def get_stock_directory():
    print(pathlib.Path().resolve)

def get_data_for_timeframe_date(
    root_dir,
    timeframe,
    date_str,
    pairs=None,
    time_col="Time",
    tz=None,
    column_map=None,
    expect_volume=False,
    debug=False,
):
    root = Path(root_dir)
    tf_candidates = {timeframe, timeframe.upper(), timeframe.lower()}

    data_map = {}
    any_globbed = []

    for tf in tf_candidates:
        # ✅ Recursive search (no explicit * in the path)
        pattern = root.rglob(f"{tf}/{date_str}/*.csv")
        matches = list(pattern)
        any_globbed.extend(matches)
        if debug:
            print(f"[DEBUG] Trying TF='{tf}' under {root} → {len(matches)} file(s)")
        for csv_path in matches:
            pair = csv_path.parent.parent.parent.name  # <pair>/<tf>/<date>/<file>.csv
            if pairs and pair not in pairs:
                continue

            df = preprocess_csv(csv_path)

            if time_col not in df.columns:
                raise ValueError(f"{csv_path} missing timestamp column '{time_col}'")

            df[time_col] = pd.to_datetime(df[time_col], errors="coerce")
            df = df.dropna(subset=[time_col]).set_index(time_col)

            if tz:
                if df.index.tz is None:
                    df.index = df.index.tz_localize(tz)
                else:
                    df.index = df.index.tz_convert(tz)

            if column_map:
                df = df.rename(columns=column_map)

            # Ensure standard OHLCV columns
            for col in ["Open", "High", "Low", "Close"]:
                if col not in df.columns:
                    raise ValueError(f"{csv_path} missing required column '{col}'")

            if "Volume" not in df.columns:
                if expect_volume:
                    raise ValueError(f"{csv_path} missing 'Volume' column.")
                df["Volume"] = 0

            df = df[["Open", "High", "Low", "Close", "Volume"]].sort_index()
            df = df[~df.index.duplicated(keep="last")]

            data_map[pair] = df

    if not data_map:
        if debug:
            print(f"[DEBUG] No matches found in {root} for {timeframe}/{date_str}")
        raise FileNotFoundError(
            f"No CSV files found in {root}/**/{timeframe}/{date_str}/ (pairs filter: {pairs})"
        )

    data_values = list(data_map.values())
    data_keys = list(data_map.keys())
    return data_keys, data_values, data_map