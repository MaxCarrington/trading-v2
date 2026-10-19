# Capture command-line arguments
# Argument 0: script name (e.g. generate_stock_data.py)
# Argument 1: --data flag (data flag)
# Argument 2: data type (either stock or forex)
# Argument 3: time frame flag (e.g. --years or --period)
# Argument 4: comma-separated years (e.g. 2010,2011,2012,2013,2014,2015,2016,2017,2018,2019,2020) or YYYY-MM-DD,YYYY-MM-DD
# Argument 5: (optional) time frame flag (e.g. --timeframe)
# Argument 6: (optional) time frame (e.g D, H4, H1, M30, M15, M5, M1)
# Argument 7: (optional) --tickers flag (if not provided, defaults to all tickers in constants.py)
# Argument 8: (optional) comma-separated tickers (e.g. AAPL,MSFT,GOOGL,AMZN)
# Run with: python scripts/run_backtest.py --config configs/backtest_smoke.yaml
#--------------------------------------------------------------------------------
import sys, os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from trading.utils.constants import YEAR_REGEX, YEAR_TIME_RANGE_REGEX, TIME_FRAMES, TICKERS, PAIRS

from trading.utils.general_utils import is_valid_regex
from trading.utils.logger import info, warning, error  # << ADD THIS
#--------------------------------------------------------------------------------


def get_data_type():
    if len(sys.argv) < 3 or sys.argv[1] != "--data":
        error("Missing or incorrect --data argument.")
        sys.exit(1)
    if sys.argv[2] not in ["stock", "forex"]:
        error("Data type must be either 'stock' or 'forex'.")
        sys.exit(1)
    return sys.argv[2]


def get_years_or_range():
    if len(sys.argv) < 5:
        error("Missing --years/--period and value.")
        sys.exit(1)

    flag = sys.argv[3]
    value = sys.argv[4]

    if flag == "--years":
        years = [y.strip() for y in value.split(",") if y.strip()]
        if not all(is_valid_regex(year, YEAR_REGEX) for year in years):
            error(f"Invalid year format: {years}")
            sys.exit(1)
        return years

    elif flag == "--period":
        if not is_valid_regex(value, YEAR_TIME_RANGE_REGEX):
            error("Period must be YYYY-MM-DD,YYYY-MM-DD.")
            sys.exit(1)
        return tuple(value.split(","))

    else:
        error("Missing or incorrect --years or --period argument.")
        sys.exit(1)


def get_time_frames():
    if len(sys.argv) >= 7 and sys.argv[5] == "--timeframe":
        frames = [tf.strip() for tf in sys.argv[6].split(",")]
        for tf in frames:
            if tf not in TIME_FRAMES:
                error(f"Time frame '{tf}' must be one of {list(TIME_FRAMES.keys())}.")
                sys.exit(1)
        return frames

    info("No --timeframe specified. Using default: D")
    return ["D"]


def get_tickers(data_type):
    if "--tickers" in sys.argv:
        index = sys.argv.index("--tickers")
        if index + 1 >= len(sys.argv):
            error("No tickers specified after --tickers flag.")
            sys.exit(1)
        return [t.strip() for t in sys.argv[index + 1].split(",") if t.strip()]
    return TICKERS if data_type == "stock" else PAIRS


def years_to_boundaries(years):
    ys = sorted({int(y) for y in years})
    bounds = [f"{y:04d}-01-01" for y in ys]
    bounds.append(f"{ys[-1] + 1:04d}-01-01")
    return bounds


def get_end_of_year(year):
    return f"{int(year):04d}-12-31"

def start():
    data_type = get_data_type()
    yr_or_rng = get_years_or_range()
    time_frames = get_time_frames()
    tickers = get_tickers(data_type)

    info(f"Data: {data_type}")
    info(f"Date Range: {yr_or_rng}")
    info(f"Timeframes: {time_frames}")
    info(f"Tickers/Pairs: {tickers}")

    if data_type == "stock":
        if any(tf in ["H1","M30","M15","M5","M1"] for tf in time_frames) and "--years" in sys.argv:
            error("For intraday stocks, use --period YYYY-MM-DD,YYYY-MM-DD.")
            sys.exit(1)

        from trading.data.data_gathering import download_stocks, download_years

        if isinstance(yr_or_rng, tuple):
            download_stocks(tickers, yr_or_rng[0], yr_or_rng[1], time_frames)
            return

        years = yr_or_rng
        if len(years) == 1:
            y = years[0]
            download_stocks(tickers, f"{y}-01-01", get_end_of_year(y), time_frames)
        else:
            boundaries = years_to_boundaries(years)
            download_years(boundaries, tickers, time_frames)

    elif data_type == "forex":
        if not isinstance(yr_or_rng, tuple):
            error("For forex, use --period YYYY-MM-DD,YYYY-MM-DD.")
            sys.exit(1)

        start_date, end_date = yr_or_rng
        selected_frames = {tf: TIME_FRAMES[tf] for tf in time_frames}

        from trading.data.data_gathering.OANDA import get_data_from_period
        get_data_from_period(start_date, end_date, time_frames=selected_frames, pairs=tickers)
        info("All data downloaded.")

start()

# Call this file from root dir using e.g: python scripts/generate_backtest_data.py --data forex --period 2025-01-01,2025-10-28 --timeframe H4,H1

''' Example call: - This will get all available data in 2025 
python scripts/generate_backtest_data.py \
  --data forex \
  --period 2024-01-01,2024-12-31 \
  --timeframe D,H4,H1,M30,M15,M5,M1
'''