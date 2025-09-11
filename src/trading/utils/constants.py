# This file defines key directory paths and constants used throughout the trading application.
import os 
# Define root and key directories
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir, os.pardir))
SRC_DIR = os.path.join(ROOT_DIR, "src")
DATA_DIR = os.path.join(ROOT_DIR, "data")
TRADING_DIR = os.path.join(SRC_DIR, "trading")
LOGS_DIR = os.path.join(ROOT_DIR, "logs")
SCIPTS_DIR = os.path.join(ROOT_DIR, "scripts")
TESTS_DIR = os.path.join(ROOT_DIR, "tests")

# Directories for storing stock and forex data
DIVIDENDS_DIR = os.path.join(DATA_DIR, "stocks", "dividends")
RAW_DATA_DIR = os.path.join(DATA_DIR, "raw")

DIVIDENDS_API_KEY = "REDACTED"

# Dictionary of time frames with their corresponding granularity and price type
TIME_FRAMES = {
    "D": {
        "granularity": 'D',  # Hourly interval
        "price": 'M',          # Midpoint prices
        "periods": 1
    },
    "H4": {
        "granularity": 'H4',  # Hourly interval
        "price": 'M',          # Midpoint prices
        "periods": 4
    },
    "H1": {
        "granularity": 'H1',  # Hourly interval
        "price": 'M',          # Midpoint prices
        "periods": 24
    },
    "M30": {
        "granularity": 'M30',  # 30-minute interval
        "price": 'M',          # Midpoint prices
        "periods": 48
    },
    "M15": {
        "granularity": 'M15',  # 15-minute interval
        "price": 'M',          # Midpoint prices
        "periods": 96
    },
    "M5": {
        "granularity": 'M5',   # 5-minute interval
        "price": 'M',          # Midpoint prices
        "periods": 288
    },
    "M1": {
        "granularity": 'M1',   # 1-minute interval
        "price": 'M',          # Midpoint prices
        "periods": 1440
    }
}

# List of currency pairs to fetch data for
PAIRS = [
    # Major Pairs
    "EUR_USD", "USD_JPY", "GBP_USD", "AUD_USD", 
    "USD_CHF", "USD_CAD", "NZD_USD",
    
    # Metals
    "XAU_USD"
]

TICKERS = [
    # US stocks
    "AAPL",   # Apple Inc.
    "MSFT",   # Microsoft Corporation
    "GOOGL",  # Alphabet Inc. (Class A)
    "AMZN",   # Amazon.com Inc.
    "NVDA",   # NVIDIA Corporation
    "TSLA",   # Tesla Inc.
    "META",   # Meta Platforms Inc.
    "BRK.B",  # Berkshire Hathaway Inc. (Class B)
    "JPM",    # JPMorgan Chase & Co.
    "JNJ",    # Johnson & Johnson

    # UK stocks (LSE tickers typically get a “.L” suffix)
    "AZN.L",  # AstraZeneca plc
    "HSBA.L", # HSBC Holdings plc
    "BP.L",   # BP plc
    "SHEL.L", # Shell plc
    "ULVR.L", # Unilever plc
    "GSK.L",  # GSK plc
    "RIO.L",  # Rio Tinto plc
    "BATS.L", # British American Tobacco plc
    "BARC.L", # Barclays plc
    "LLOY.L"  # Lloyds Banking Group plc
]

YEARS = [
    "2015-01-01",
    "2016-01-01",
    "2017-01-01",
    "2018-01-01",
    "2019-01-01",
    "2020-01-01",
    "2021-01-01",
    "2022-01-01",
    "2023-01-01",
    "2024-01-01",
    "2025-01-01",
    "2026-01-01"
]

# Map your time_frame to yfinance interval strings
YF_INTERVAL = {
    "D":   "1d",   # yfinance has no 4h
    "H1":  "60m",
    "M30": "30m",
    "M15": "15m",
    "M5":  "5m",
    "M1":  "1m",
}
# Regular expression consiststing of a time frame range between two years in YYYY-MM-DD format
YEAR_TIME_RANGE_REGEX = r"^\d{4}-\d{2}-\d{2},\d{4}-\d{2}-\d{2}$"

# Regular expression for validating a single date in YYYY-MM-DD format
DATE_REGEX = r"^\d{4}-\d{2}-\d{2}$"

# Regular expression for validating a single year in YYYY format
YEAR_REGEX = r"^\d{4}$"