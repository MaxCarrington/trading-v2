import os
import yfinance as yf
import trading.utils.constants as constants
from trading.utils.paths import get_stock_dir
from datetime import datetime, timedelta

from datetime import datetime, timedelta

def validate_window(start_date, interval):
    today = datetime.utcnow().date()
    start = datetime.fromisoformat(start_date).date()

    limits = {"1m": 30, "2m": 60, "5m": 60, "15m": 60, "30m": 60, "60m": 730}
    if interval in limits:
        cutoff = today - timedelta(days=limits[interval])
        if start < cutoff:
            raise ValueError(
                f"{interval} data only available for last {limits[interval]} days. "
                f"You requested {start_date}, which is too old."
            )


def get_interval(time_frame):
    if time_frame in constants.YF_INTERVAL:
        return constants.YF_INTERVAL[time_frame]
    else:
        raise ValueError(f"Unsupported time frame: {time_frame}")
# Downloads a list of stocks within a particular time frame, between a specific start and end date 
def download_stocks(tickers_arr, start_date, end_date, time_frame): 
    interval = get_interval(time_frame)
    
    for ticker in tickers_arr:
        try:
            validate_window(start_date, interval)
            info(f"Downloading {ticker} data from {start_date} to {end_date} with interval {interval}...") 
            data = yf.download(ticker, start=start_date, end=end_date, interval=interval)
            if not data.empty:
                folder_path = get_stock_dir("yahoo", ticker, time_frame, start_date)
                # Construct the full directory path
                if not os.path.exists(folder_path):
                    os.makedirs(folder_path)
                # Now build the full file path and save the data
                file_path = os.path.join(folder_path, f"{ticker}.csv")
                data.to_csv(file_path)

                info(f"Saved {ticker} data to {file_path}")
            else:
                info(f"No data for {ticker}")
        except Exception as e:
            info(f"Error downloading {ticker}: {e}")

# Downloads a list of stocks over a list of years
def download_years(years_arr, tickers_arr, time_frame):
    for x in range(len(years_arr) - 1):
        try:
            info(f"Downloading data from: {years_arr[x]}...")
            start = years_arr[x]
            end = years_arr[x+1]
            download_stocks(tickers_arr, start, end, time_frame)
        except Exception as e:
            info(f"Error downloading data from: {years_arr[x]}: {e}")




