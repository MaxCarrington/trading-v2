import sys
import os
import requests
import json

from trading.utils.paths import get_dividends_api_key, get_data_dir
from trading.utils.paths import get_dividend_file
import trading.utils.constants as constants

# Dynamically add the project root to PYTHONPATH
sys.path.append(constants.PROJECT_ROOT)

stock_data_path = os.path.join(get_data_dir(), "StockData") 

tickers = [
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

def download_dividend_info(symbol):
    url = f'https://www.alphavantage.co/query?function=DIVIDENDS&symbol={symbol}&apikey={get_dividends_api_key()}'
    r = requests.get(url)
    data = r.json()

    # Construct the full directory path
    folder_path = os.path.join(f"{constants.DIVIDENDS_DIR}", symbol)
    os.makedirs(folder_path, exist_ok=True)

    # Define the output file path
    file_path = os.path.join(folder_path, f"{symbol}_dividends.json")

    # Save the JSON data
    with open(file_path, 'w') as f:
        json.dump(data, f, indent=4)

    print(f"Dividend data saved to {file_path}")

# Example usage
for ticker in tickers:
    download_dividend_info(ticker)

def get_dividend_dates(symbol):
    dates = []
    dividends = get_dividend_file(symbol)
    print(dividends)

    # Load from file
    with open(dividends) as f:
        data = json.load(f)

    # Access metadata
    symbol = data["symbol"]

    print(f"Symbol: {symbol}")
    # Access dividend records
    for entry in data["data"]:
        dec_date = entry["declaration_date"]
        pay_date = entry["payment_date"]
        print(f"{symbol} Declaration date {dec_date}, payment date: ${pay_date}")
        if not (dec_date == "None" or pay_date == "None"):
            date_tuple = (dec_date, pay_date)
            dates.append(date_tuple)
    
    return dates