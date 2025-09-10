import os 
import pandas as pd

# Define root and key directories
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
print("Root dir:", ROOT_DIR)
SRC_DIR = os.path.join(ROOT_DIR, "src")
DATA_DIR = os.path.join(ROOT_DIR, "data")
TRADING_DIR = os.path.join(SRC_DIR, "trading")
LOGS_DIR = os.path.join(ROOT_DIR, "logs")
SCIPTS_DIR = os.path.join(ROOT_DIR, "scripts")
TESTS_DIR = os.path.join(ROOT_DIR, "tests")

# Directories for storing stock and forex data
DIVIDENDS_DIR = os.path.join(DATA_DIR, "stocks", "dividends")
DAY_DATA_DIR = os.path.join(DATA_DIR, "stocks", "daily")
DAILY_FOREX_DATA = os.path.join(DATA_DIR, "forex", "daily")

DIVIDENDS_API_KEY = "REDACTED"

# Dictionary of time frames with their corresponding granularity and price type
time_frames = {
    "D": {
        "granularity": 'D',  # Hourly interval
        "price": 'M'          # Midpoint prices
    },
    "H4": {
        "granularity": 'H4',  # Hourly interval
        "price": 'M'          # Midpoint prices
    },
    "H1": {
        "granularity": 'H1',  # Hourly interval
        "price": 'M'          # Midpoint prices
    },
    "M30": {
        "granularity": 'M30',  # 30-minute interval
        "price": 'M'          # Midpoint prices
    },
    "M15": {
        "granularity": 'M15',  # 15-minute interval
        "price": 'M'          # Midpoint prices
    },
    "M5": {
        "granularity": 'M5',   # 5-minute interval
        "price": 'M'          # Midpoint prices
    },
    "M1": {
        "granularity": 'M1',   # 1-minute interval
        "price": 'M'          # Midpoint prices
    }
}

# List of currency pairs to fetch data for
pairs = [
    # Major Pairs
    "EUR_USD", "USD_JPY", "GBP_USD", "AUD_USD", 
    "USD_CHF", "USD_CAD", "NZD_USD",
    
    # Metals
    "XAU_USD"
]

# Get the logs directory
def get_logs_dir():
    return LOGS_DIR

# Get the scripts directory
def get_scripts_dir():
    return SCIPTS_DIR

# Get the tests directory
def get_tests_dir():  
    return TESTS_DIR

# Get the dictionary of time frames
def get_time_frames():
    return time_frames

# Get the list of currency pairs
def get_pairs():
    return pairs

# Get the dividends API key
def get_dividends_api_key():
    return DIVIDENDS_API_KEY

# Get the root directory
def get_root_dir():
    return ROOT_DIR

# Get the trading directory
def get_trading_dir():
    return TRADING_DIR

# Get the src directory
def get_src_dir():
    return SRC_DIR

# Get the data directory
def get_data_dir():
    return DATA_DIR

# Get the dividends directory
def get_dividends_dir():
    return DIVIDENDS_DIR

# Get the daily stock data directory
def get_daily_stock_data_dir():
    return DAY_DATA_DIR

# Get the daily forex data directory
def get_daily_forex_data_dir():
    return DAILY_FOREX_DATA

# Load a dividend file for a given stock symbol and return the file path.
def get_dividend_file(symbol):
    dividend_path = os.path.join(DIVIDENDS_DIR, symbol)
    
    if not os.path.isdir(dividend_path):
        raise FileNotFoundError(f"Directory for symbol '{symbol}' not found at path: {dividend_path}")
    else:
        dividends_file = os.path.join(dividend_path, f"{symbol}_dividends.json")
        if not os.path.isfile(dividends_file):
            raise FileNotFoundError(f"Dividend file for symbol '{symbol}' not found at path: {dividends_file}")
    
    return dividends_file

# Load a daily stock time series from CSV in a given year and return the file path.
def get_time_series_file_path(symbol, year):
    time_series_path = os.path.join(DAY_DATA_DIR, year, symbol)

    if not os.path.isdir(time_series_path):
        raise FileNotFoundError(f"Directory for symbol '{symbol}' not found at path: {time_series_path}")
    else:
        time_series_file = os.path.join(time_series_path, f"{symbol}.csv")
        if not os.path.isfile(time_series_file):
            raise FileNotFoundError(f"Time series file for symbol '{symbol}' not found at path: {time_series_file}")
    
    return time_series_file 

# Load a daily forex time series from CSV and return as a DataFrame.
def get_daily_forex_data_df(date, time_frame, pair):
    time_frame_data = os.path.join(DAILY_FOREX_DATA, date, time_frame)
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
    print(df)
    print(start_date)
    print(end_date)
    return df.loc[start_date:end_date]                 # vectorised slice, keeps every column

# Stack df2 directly under df1, keeping all columns and dates.
def stitch_dataframes(df1, df2):
    print("Stitching")
    return pd.concat([df1, df2]).sort_index()