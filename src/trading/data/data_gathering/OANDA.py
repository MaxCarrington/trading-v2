

import os
import pandas as pd
import oandapyV20.endpoints.instruments as instruments
import trading.utils.constants as constants

from datetime import datetime, timedelta
from oandapyV20 import API
from trading.utils.paths import get_forex_dir, get_time_frames, get_pairs

# Initialize API client
client = API(access_token='REDACTED', environment='practice')

# Fetches and saves OANDA forex OHLCV data for all pairs and timeframes
# on the given date (YYYY-MM-DD), storing each pair’s data as a CSV.
def get_daily_data_for_date(date, time_frames, pairs):
    # Parse the input date and calculate the start and end time for the day in UTC
    date_start = datetime.strptime(date, '%Y-%m-%d')
    start_time = date_start.replace(hour=0, minute=0, second=0, microsecond=0)
    end_time = start_time + timedelta(days=1) - timedelta(seconds=1)  # End of the day

    # Fetch data for the specified date
    for time_frame_key, params in time_frames.items():
        for pair in pairs:
            # Define API request parameters
            api_params = {
                "from": start_time.isoformat() + "Z",
                "to": end_time.isoformat() + "Z",
                "granularity": params["granularity"],
                "price": params["price"]
            }
            # Fetch the data
            r = instruments.InstrumentsCandles(instrument=pair, params=api_params)
            data = client.request(r)
            # Parse data into DataFrame
            rows = []
            for candle in data.get('candles', []):
                if candle['complete'] and 'mid' in candle:
                    mid = candle['mid']
                    row = [candle['time'], mid['o'], mid['h'], mid['l'], mid['c'], candle['volume']]
                    rows.append(row)

            df = pd.DataFrame(rows, columns=['Time', 'Open', 'High', 'Low', 'Close', 'Volume'])
            df['Time'] = pd.to_datetime(df['Time'])

            # Organize data into daily folder
            forex_folder = get_forex_dir("oanda", pair, time_frame_key, start_time)

            if not os.path.exists(forex_folder):
                os.makedirs(forex_folder)

            file_name = f"{pair}.csv" # Change from OANDA API pair format to normal format
            file_path = os.path.join(forex_folder, file_name)
            print(file_path)

            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            # Save DataFrame to CSV
            df.to_csv(file_path, index=False)
            print(f"Data saved for {pair} in {file_path}")

# Fetches data for all timeframes for each day over a date range
def get_data_from_period(start_date, end_date, time_frames=get_time_frames(), pairs=get_pairs()):
    # Ensure datetime objects
    if isinstance(start_date, str):
        start_date = datetime.strptime(start_date, "%Y-%m-%d")
    if isinstance(end_date, str):
        end_date = datetime.strptime(end_date, "%Y-%m-%d")

    current_date = start_date
    while current_date <= end_date:
        date_str = current_date.strftime('%Y-%m-%d')
        print(f"Fetching data for {date_str}...")

        get_daily_data_for_date(date_str, time_frames, pairs)

        print(f"Completed fetching data for {date_str}.\n")
        current_date += timedelta(days=1)



