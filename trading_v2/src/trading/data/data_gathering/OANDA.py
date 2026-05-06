import os
import pandas as pd
import oandapyV20.endpoints.instruments as instruments

from datetime import datetime, timedelta
from oandapyV20 import API
from trading.utils.paths import get_forex_dir, get_time_frames, get_pairs

# Initialize API client
client = API(access_token='REDACTED', environment='practice')

def _fmt_utc(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

def get_daily_data_for_date(date, time_frames, pairs):
    date_start = datetime.strptime(date, '%Y-%m-%d')
    start_time = date_start.replace(hour=0, minute=0, second=0, microsecond=0)
    end_time = start_time + timedelta(days=1) - timedelta(seconds=1)

    for time_frame_key, params in time_frames.items():
        for pair in pairs:

            api_params = {
                "from": _fmt_utc(start_time),
                "to": _fmt_utc(end_time),
                "granularity": params["granularity"],
                "price": params["price"],  # now "BAM"
            }

            r = instruments.InstrumentsCandles(instrument=pair, params=api_params)
            data = client.request(r)

            rows = []
            for candle in data.get('candles', []):
                bid = candle.get("bid")
                ask = candle.get("ask")
                mid = candle.get("mid")

                if candle.get("complete") and bid and ask and mid:
                    rows.append([
                        candle["time"],

                        # Bid OHLC
                        bid["o"], bid["h"], bid["l"], bid["c"],

                        # Ask OHLC
                        ask["o"], ask["h"], ask["l"], ask["c"],

                        # Mid OHLC
                        mid["o"], mid["h"], mid["l"], mid["c"],

                        # Spread (close)
                        float(ask["c"]) - float(bid["c"]),

                        candle["volume"],
                    ])

            df = pd.DataFrame(rows, columns=[
                "Time",
                "BidOpen", "BidHigh", "BidLow", "BidClose",
                "AskOpen", "AskHigh", "AskLow", "AskClose",
                "MidOpen", "MidHigh", "MidLow", "MidClose",
                "SpreadClose",
                "Volume",
            ])

            df["Time"] = (
                pd.to_datetime(df["Time"], utc=True)
                .dt.tz_convert(None)  # make it naive but UTC-based
            )
            # ----- NEW FOLDER STRUCTURE -----
            # pair/year/timeframe
            pair_folder = os.path.dirname(os.path.dirname(get_forex_dir("oanda", pair, time_frame_key, start_time)))
            year_folder = os.path.join(pair_folder, str(start_time.year), time_frame_key)

            # Daily folder as MM-DD
            daily_folder = os.path.join(year_folder, start_time.strftime("%m-%d"))
            os.makedirs(daily_folder, exist_ok=True)

            # Save daily CSV
            file_path = os.path.join(daily_folder, f"{pair}.csv")
            df.to_csv(file_path, index=False)
            print(f"Daily data saved at {file_path}")

            # ----- MERGED YEARLY DATA -----
            merged_folder = os.path.join(year_folder, "merged")
            os.makedirs(merged_folder, exist_ok=True)
            merged_file = os.path.join(merged_folder, f"{pair}_{start_time.year}.csv")

            if os.path.exists(merged_file):
                df.to_csv(merged_file, mode="a", header=False, index=False)
            else:
                df.to_csv(merged_file, index=False)

            merged_df = pd.read_csv(merged_file)
            merged_df = merged_df.drop_duplicates(subset=["Time"]).sort_values("Time")
            merged_df.to_csv(merged_file, index=False)

            print(f"Merged data updated at {merged_file}")


def get_data_from_period(start_date, end_date, time_frames=get_time_frames(), pairs=get_pairs()):
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

''' Example call: - This will get all available data in 2025 
python scripts/generate_backtest_data.py \
  --data forex \
  --period 2025-01-01,2025-12-31 \
  --timeframe D,H4,H1,M30,M15,M5,M1
'''