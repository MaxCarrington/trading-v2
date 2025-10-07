import re 
import pandas as pd
from pathlib import Path
import src.trading.utils.paths as paths
from datetime import date, timedelta

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
    base_dir = Path(paths.get_forex_dir(provider, pair, time_frame))
    frames = []

    for d in get_date_range(start_date, end_date):
        csv_path = base_dir / d.strftime("%Y-%m-%d") / f"{pair}.csv"
        if csv_path.exists():
            # if you have your own reader, use it: df = from_csv_to_df(csv_path)
            df = pd.read_csv(csv_path)
            frames.append(df)

    if not frames:
        return pd.DataFrame()

    # One concat at the end; keep rows in date order; drop index gaps
    out = pd.concat([f for f in frames if not f.empty], ignore_index=True)
    return out