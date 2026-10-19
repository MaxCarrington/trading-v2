import os
import time
import pandas as pd
import oandapyV20.endpoints.instruments as instruments

from datetime import datetime, timedelta
from dotenv import load_dotenv
from oandapyV20 import API
from trading.utils.paths import get_forex_dir, get_time_frames, get_pairs
from pandas.errors import EmptyDataError

from trading.utils.logger import info, warning, error

load_dotenv()

INDICES = {"SPX500_USD", "DE30_EUR", "UK100_GBP", "JP225_USD", "NAS100_USD", "US30_USD"}
MAX_CANDLES = 5000

client = API(
    access_token=os.environ["OANDA_API_TOKEN"],
    environment=os.environ.get("OANDA_ENVIRONMENT", "practice"),
)

COLUMNS = [
    "Time",
    "BidOpen", "BidHigh", "BidLow", "BidClose",
    "AskOpen", "AskHigh", "AskLow", "AskClose",
    "MidOpen", "MidHigh", "MidLow", "MidClose",
    "SpreadClose",
    "Volume",
]


def _fmt_utc(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def candles_to_df(candles):
    rows = []
    for candle in candles:
        bid = candle.get("bid")
        ask = candle.get("ask")
        mid = candle.get("mid")

        if candle.get("complete") and bid and ask and mid:
            rows.append([
                candle["time"],
                bid["o"], bid["h"], bid["l"], bid["c"],
                ask["o"], ask["h"], ask["l"], ask["c"],
                mid["o"], mid["h"], mid["l"], mid["c"],
                float(ask["c"]) - float(bid["c"]),
                candle["volume"],
            ])

    df = pd.DataFrame(rows, columns=COLUMNS)
    df["Time"] = pd.to_datetime(df["Time"], utc=True).dt.tz_convert(None)  # naive but UTC-based
    return df


def get_merged_file(pair, time_frame_key, year):
    # pair/year/timeframe/merged/pair_year.csv
    pair_folder = os.path.dirname(os.path.dirname(get_forex_dir("oanda", pair, time_frame_key, datetime(year, 1, 1))))
    if pair in INDICES:
        pair_folder = pair_folder.replace(os.sep + "forex" + os.sep, os.sep + "indices" + os.sep)

    merged_folder = os.path.join(pair_folder, str(year), time_frame_key, "merged")
    os.makedirs(merged_folder, exist_ok=True)
    return os.path.join(merged_folder, f"{pair}_{year}.csv")


def request_candles(pair, params, start):
    # one API call with retry and backoff
    api_params = {
        "from": _fmt_utc(start),
        "count": MAX_CANDLES,
        "granularity": params["granularity"],
        "price": params["price"],  # "BAM"
    }
    wait = 10
    while True:
        try:
            r = instruments.InstrumentsCandles(instrument=pair, params=api_params)
            return client.request(r).get("candles", [])
        except Exception as e:
            warning(f"{pair} {params['granularity']} from {start}: {type(e).__name__}. Retrying in {wait}s...")
            time.sleep(wait)
            wait = min(wait * 2, 300)


def get_data_for_year(pair, time_frame_key, params, year, start, end):
    start = max(start, datetime(year, 1, 1))
    end = min(end, datetime(year + 1, 1, 1), datetime.utcnow())

    frames = []
    while start < end:
        candles = request_candles(pair, params, start)
        if not candles:
            break
        frames.append(candles_to_df(candles))
        last = pd.to_datetime(candles[-1]["time"], utc=True).tz_convert(None).to_pydatetime()
        if last < start:
            break
        start = last + timedelta(seconds=1)
        time.sleep(0.2)

    if not frames:
        warning(f"No data for {pair} {time_frame_key} {year}")
        return

    df = pd.concat(frames, ignore_index=True)
    df = df[df["Time"] < end]

    # merge with what's already saved, so re-running only tops it up
    merged_file = get_merged_file(pair, time_frame_key, year)
    if os.path.exists(merged_file):
        try:
            old = pd.read_csv(merged_file, parse_dates=["Time"])
            df = pd.concat([old, df], ignore_index=True)
        except EmptyDataError:
            pass

    df = df.drop_duplicates(subset=["Time"], keep="last").sort_values("Time")
    df.to_csv(merged_file, index=False)
    info(f"Saved {len(df)} rows to {merged_file}")


def get_data_from_period(start_date, end_date, time_frames=get_time_frames(), pairs=get_pairs()):
    if isinstance(start_date, str):
        start_date = datetime.strptime(start_date, "%Y-%m-%d")
    if isinstance(end_date, str):
        end_date = datetime.strptime(end_date, "%Y-%m-%d")
    end_date = end_date + timedelta(days=1)  # include the end day

    for time_frame_key, params in time_frames.items():
        for pair in pairs:
            for year in range(start_date.year, end_date.year + 1):
                info(f"Fetching {pair} {time_frame_key} {year}...")
                get_data_for_year(pair, time_frame_key, params, year, start_date, end_date)