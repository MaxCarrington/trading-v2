import os
import re
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import date, timedelta, datetime

from trading.utils import constants
from trading.utils.logger import error, info, warning
from trading.utils.paths import get_forex_dir
# Converts a csv file to a data frame, localising the time zone
def from_csv_to_df(file_name, keep_time_zone=False):
    df = pd.read_csv(
        file_name,
        parse_dates=["Time"],
        index_col="Time"
    )
    if not keep_time_zone:
        # Remove timezone (convert to naive datetime)
        df.index = df.index.tz_localize(None)

    return df

# keep_bid_ask=True also keeps the BidOpen..AskClose columns (for the bid_ask cost model)
def load_mid_ohlcv(path: str, keep_bid_ask: bool = False) -> pd.DataFrame:
    raw = pd.read_csv(path, parse_dates=["Time"])

    # Case 1: New 15-column BAM format with Mid/Bid/Ask
    if "MidOpen" in raw.columns:
        df = raw.copy()

        # If Spread column isn't already there, derive it
        if "Spread" not in df.columns:
            if "AskClose" in df.columns and "BidClose" in df.columns:
                df["Spread"] = df["AskClose"].astype(float) - df["BidClose"].astype(float)
            else:
                # Fallback if somehow BAM is partial
                df["Spread"] = np.nan

        df = df.rename(columns={
            "MidOpen":  "Open",
            "MidHigh":  "High",
            "MidLow":   "Low",
            "MidClose": "Close",
        })

        # Keep OHLCV + Spread for downstream
        cols = ["Time", "Open", "High", "Low", "Close", "Volume", "Spread"]
        if keep_bid_ask:
            cols += [f"{side}{p}" for side in ("Bid", "Ask") for p in ("Open", "High", "Low", "Close")]
        df = df[cols]

    else:
        # Case 2: Old OHLCV-only or OHLCV+Spread format
        base_cols = ["Time", "Open", "High", "Low", "Close", "Volume"]
        extra_cols = []

        # If Spread already exists in the CSV, keep it; otherwise we'll just omit it
        if "Spread" in raw.columns:
            extra_cols.append("Spread")

        df = raw[base_cols + extra_cols]

        # If no Spread, you can optionally create a dummy column:
        if "Spread" not in df.columns:
            df["Spread"] = np.nan  # or a fixed value if you want a default

    return df.set_index("Time")

def load_mid_ohlcv_range(pair, year, timeframe, start_mmdd, end_mmdd):
    """Load and stitch daily mid-OHLCV CSVs across a date range."""
    start = datetime.strptime(f"{year}-{start_mmdd}", "%Y-%m-%d")
    end   = datetime.strptime(f"{year}-{end_mmdd}",   "%Y-%m-%d")

    base = os.path.join(constants.OANDA_FOREX_DATA_DIR, pair, str(year), timeframe)

    frames = []
    current = start
    while current <= end:
        date_str = current.strftime("%m-%d")
        path = os.path.join(base, date_str, f"{pair}.csv")
        if os.path.isfile(path):                    # silently skip missing days (weekends/holidays)
            frames.append(load_mid_ohlcv(path))     # ← reuses the renamer
        current += timedelta(days=1)

    if not frames:
        raise FileNotFoundError(f"No daily CSVs found for {pair} between {start_mmdd} and {end_mmdd} in {year}")

    combined = pd.concat(frames).sort_index()
    return combined

# Validate if a value matches a given regex pattern
def is_valid_regex(value, regex):
    return bool(re.fullmatch(regex, value))

# Define trading sessions
def get_trading_session_folder(time):
    if time.hour >= 7 and time.hour < 15:  # London session
        return "London"
    elif time.hour >= 15 and time.hour < 23:  # New York session
        return "New_York"
    else:  # Asian session
        return "Asian"

# Stack df2 directly under df1, keeping all columns and dates.
def stitch_dataframes(df1, df2):
    return pd.concat([df1, df2]).sort_index()

def get_date_range(start_date: date, end_date: date):
    days = (end_date - start_date).days
    for n in range(days + 1):        # inclusive of end_date
        yield start_date + timedelta(n)

def stitch_data_from_period(start_date, end_date, provider, pair, time_frame):
    base_dir = Path(get_forex_dir(provider, pair, time_frame))
    frames = []

    info(f"Stitching data for {pair} from {start_date.date()} to {end_date.date()} using timeframe {time_frame}")

    for d in get_date_range(start_date, end_date):
        csv_path = base_dir / d.strftime("%Y-%m-%d") / f"{pair}.csv"
        if csv_path.exists():
            try:
                df = pd.read_csv(csv_path)
                if "Time" in df.columns:
                    df["Time"] = pd.to_datetime(df["Time"], errors="coerce")
                    df = df.dropna(subset=["Time"]).set_index("Time")
                    df = df[["Open", "High", "Low", "Close", "Volume"]].sort_index()
                    df = df[~df.index.duplicated(keep="last")]
                frames.append(df)
                info(f"Loaded {csv_path.name} on date {d.date()} with {len(df)} rows")
            except Exception as e:
                warning(f"Failed to process {csv_path.name}: {e}")
        else:
            warning(f"Missing file: {csv_path}")

    if not frames:
        warning(f"No data frames collected for {pair}")
        return [], [], {}

    valid_frames = [f for f in frames if not f.empty]
    if not valid_frames:
        warning(f"All frames empty for {pair}")
        return pd.DataFrame()

    stitched_df = pd.concat(valid_frames, axis=0).sort_index()

    if stitched_df.index.tz is not None:
        stitched_df.index = stitched_df.index.tz_convert(None)

    data_keys = [pair]
    data_values = [stitched_df]
    data_map = {pair: stitched_df}
    info(f"Stitched {len(stitched_df)} total rows for {pair}")
    return data_keys, data_values, data_map
