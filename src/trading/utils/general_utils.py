import re 
import pandas as pd
from pathlib import Path
import src as paths
from datetime import date, timedelta
from src.trading.utils.logger import error, info, warning
from src.trading.utils.paths import get_forex_dir
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
