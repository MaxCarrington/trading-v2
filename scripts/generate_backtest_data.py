import sys
import trading.utils.constants as constants

from trading.utils.general_utils import is_valid_regex
#--------------------------------------------------------------------------------
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
# Run with: python scripts/run_backtest.py --config configs/backtest_config.yaml
#--------------------------------------------------------------------------------

# Validate and parse command-line arguments, to determine if downloading stock or forex data
def get_data_type():
    if len(sys.argv) < 3 or sys.argv[1] != "--data":
        print("Error: Missing or incorrect --data argument.")
        sys.exit(1)
    if sys.argv[2] not in ["stock", "forex"] or sys.argv[2] is None:
        print("Error: Data type must be either 'stock' or 'forex'.")
        sys.exit(1)

    return sys.argv[2]

# Validate and parse command-line arguments, to determine years or a time range
def get_years_or_range():
    if len(sys.argv) < 5:
        print("Error: Missing --years/--period and value.")
        sys.exit(1)

    flag = sys.argv[3]
    value = sys.argv[4]

    if flag == "--years":
        years = [y.strip() for y in value.split(",") if y.strip()]
        if not all(is_valid_regex(year, constants.YEAR_REGEX) for year in years):
            print(years)
            print("Error: Years must be in YYYY format.")
            sys.exit(1)
        return years  # list[str]

    elif flag == "--period":
        if not is_valid_regex(value, constants.YEAR_TIME_RANGE_REGEX):
            print("Error: Period must be YYYY-MM-DD,YYYY-MM-DD.")
            sys.exit(1)
        start_date, end_date = [p.strip() for p in value.split(",")]
        return (start_date, end_date)  # tuple[str, str]

    else:
        print("Error: Missing or incorrect --years or --period argument.")
        sys.exit(1)

# Validate and parse command-line arguments, to determine the time frame
def get_time_frame():
    if len(sys.argv) >= 7 and sys.argv[5] == "--timeframe":
        tf = sys.argv[6]
        if tf not in constants.TIME_FRAMES or tf is None:
            print(f"Error: Time frame must be one of {list(constants.TIME_FRAMES.keys())}.")
            sys.exit(1)
        return tf

    # Default to daily
    default_tf = "D"
    print(f"No --timeframe specified. Using default: {default_tf}")
    return default_tf



# Validate and parse command-line arguments, to determine the tickers or pairs
def get_tickers(data_type):
    if data_type == "stock":
        if "--tickers" in sys.argv:
            i = sys.argv.index("--tickers")
            if i + 1 >= len(sys.argv):
                print("Error: --tickers flag provided but no tickers specified.")
                sys.exit(1)
            return [t.strip() for t in sys.argv[i + 1].split(",") if t.strip()]
        return constants.TICKERS
    else:
        return constants.PAIRS
    
# Convert years to year-start boundaries + closing boundary
def years_to_boundaries(years):
    ys = sorted({int(y) for y in years})  # sort + de-dup
    bounds = [f"{y:04d}-01-01" for y in ys]
    bounds.append(f"{ys[-1] + 1:04d}-01-01")  # cap the last year
    return bounds

def get_end_of_year(year):
    return f"{int(year):04d}-12-31"

def start():
    data_type = get_data_type()
    yr_or_rng = get_years_or_range()   # list[str] (years) OR tuple[str,str] (period)
    time_frame = get_time_frame()
    tickers = get_tickers(data_type)

    print(f"Data type: {data_type}")
    print(f"Years or Range: {yr_or_rng}")
    print(f"Time Frame: {time_frame}")
    print(f"Tickers/Pairs: {tickers}")

    if data_type == "stock":
        if data_type == "stock":
            if time_frame in ["H1", "M30", "M15", "M5", "M1"] and "--years" in sys.argv:
                print("Error: For intraday timeframes, please use --period YYYY-MM-DD,YYYY-MM-DD.")
                sys.exit(1)

        from trading.data.YahooFinance import download_stocks, download_years

        # Case 1: --period (already full dates)
        if isinstance(yr_or_rng, tuple) and len(yr_or_rng) == 2:
            start_date, end_date = yr_or_rng
            download_stocks(tickers, start_date, end_date, time_frame)
            return

        # From here it's --years (list of YYYY strings)
        years = yr_or_rng

        if len(years) == 1:
            y = years[0]
            start_date = f"{int(y):04d}-01-01"
            end_date   = get_end_of_year(y)
            download_stocks(tickers, start_date, end_date, time_frame)

        elif len(years) >= 2:
            # Build boundaries so download_years fetches each full year
            boundaries = years_to_boundaries(years)
            # download_years expects a list of dates where it uses [i]..[i+1]
            download_years(boundaries, tickers, time_frame)

        else:
            print("Error: No years provided.")
            sys.exit(1)

    elif data_type == "forex":
        from trading.data.OANDA import get_data_from_period
        if isinstance(yr_or_rng, tuple) and len(yr_or_rng) == 2:
            start_date, end_date = yr_or_rng
            get_data_from_period(start_date, end_date)
        else:
            print("Error: For forex use --period YYYY-MM-DD,YYYY-MM-DD.")
            sys.exit(1)


start()
    
