import os
from datetime import datetime
import pandas as pd
import trading.utils.constants as constants

# Get the number of periods for a given time frame
def get_num_time_frame_periods(time_frame):
    if time_frame in constants.TIME_FRAMES:
        return constants.TIME_FRAMES[time_frame]["periods"]

# Get the directory path for daily forex data for a given day
def get_forex_dir(provider, pair, time_frame, start=None):
    if not isinstance(start, str) and start is not None:
        start = start.strftime("%Y-%m-%d")
    if start is None:
        return os.path.join(constants.RAW_DATA_DIR, provider, "forex", pair, time_frame)
    else:
        return os.path.join(constants.RAW_DATA_DIR, provider, "forex", pair, time_frame, start)

# Get the directory path for daily stock data for a given day and symbol
def get_stock_dir(provider, symbol, time_frame, start):
    return os.path.join(constants.RAW_DATA_DIR, provider, "stocks", symbol, time_frame, start)

def get_raw_data_dir():
    return constants.RAW_DATA_DIR

# Get the logs directory
def get_logs_dir():
    return constants.LOGS_DIR

# Get the results directory (root of all per-run backtest output)
def get_results_dir():
    return constants.RESULTS_DIR

# Create (if needed) and return the folder for a single backtest run:
# results/<strategy_name>/<run_id>/
# Everything produced by that run — trades.csv, config.yaml, metrics.json,
# report.html, figures/ — lives together in this one folder.
def create_run_dir(strategy_name, run_id=None):
    if run_id is None:
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = os.path.join(constants.RESULTS_DIR, strategy_name, run_id)
    os.makedirs(run_dir, exist_ok=True)
    return run_dir

# Get the scripts directory
def get_scripts_dir():
    return constants.SCIPTS_DIR

# Get the tests directory
def get_tests_dir():  
    return constants.TESTS_DIR

# Get the dictionary of time frames
def get_time_frames():
    return constants.TIME_FRAMES

# Get the list of currency pairs
def get_pairs():
    return constants.PAIRS

# Get the root directory
def get_root_dir():
    return constants.ROOT_DIR

# Get the trading directory
def get_trading_dir():
    return constants.TRADING_DIR

# Get the src directory
def get_src_dir():
    return constants.SRC_DIR

# Get the data directory
def get_data_dir():
    return constants.DATA_DIR

# Load a daily stock time series from CSV in a given year and return the file path.
def get_time_series_file_path(symbol, year):
    time_series_path = os.path.join(constants.DAY_DATA_DIR, year, symbol)

    if not os.path.isdir(time_series_path):
        raise FileNotFoundError(f"Directory for symbol '{symbol}' not found at path: {time_series_path}")
    else:
        time_series_file = os.path.join(time_series_path, f"{symbol}.csv")
        if not os.path.isfile(time_series_file):
            raise FileNotFoundError(f"Time series file for symbol '{symbol}' not found at path: {time_series_file}")
    
    return time_series_file 

# Load a daily forex time series from CSV and return as a DataFrame.
def get_daily_forex_data_df(date, time_frame, pair):
    time_frame_data = os.path.join(constants.DAILY_FOREX_DATA, date, time_frame)
    if not os.path.isdir(time_frame_data):
        raise FileNotFoundError(f"Directory not found at path: {time_frame_data}")
    else:
        data_csv = os.path.join(time_frame_data, f"{pair}.csv")
        if not os.path.isfile(data_csv):
            raise FileNotFoundError(f"Time series file for pair '{pair}' not found at path: {data_csv}")

    df = pd.read_csv(data_csv)
    return df

# Load a time series from CSV, slice it to the given date range, and return the result.
def get_time_series_period_df(data_path, start_date, end_date):

    df = (
        pd.read_csv(
            data_path,
            skiprows=[1, 2],           # drop the “Ticker, …” and “Date, …” rows
            parse_dates=["Price"],     # turn the first column into real datetimes
        )
    .rename(columns={"Price": "Date"})   # clearer column name
    .set_index("Date")                   # makes date slicing ultra-fast
    )
    info(df)
    info(start_date)
    info(end_date)
    return df.loc[start_date:end_date]                 # vectorised slice, keeps every column

# Saves content to a file at a specific directory
def save_to_file(dir, file_name, content):
    # Ensure the directory exists
    if not os.path.isdir(dir):
        os.makedirs(dir, exist_ok=True)

    file_path = os.path.join(dir, file_name)

    # Write content to the file
    with open(file_path, 'w') as f:
        f.write(content)

    info(f"File saved to: {file_path}")

