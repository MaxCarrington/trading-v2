# JSON format:
# symbol: This is the stock ticker.
# ex_dividend_date: The date by which you must own the stock to receive the dividend. If you buy the stock on or after this date, you won’t get the dividend.
# declaration_date: The date the company announces the dividend and its amount.
# record_date: The company looks at its shareholder records on this date to determine who gets the dividend.
# payment_date: The date the dividend is actually paid out to shareholders.
# amount: The cash amount paid per share—in this case, $ USD per share.

import json
import sys
from Utilities.definitions import get_dividend_file, get_time_series, get_time_series_period_df, stitch
# Returns the dividend dates for a stock, removing any years there were no dicidents
# return format: [(declaration date, payment date)]
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

def test_day():
    return(1)

# Gets all time series data from the period between dividend declaration date and payment date 
def test_period(symbol):
    dividend_dates = get_dividend_dates(symbol)
    dividend_years = convert_to_jan_first(dividend_dates)

    counter = 0

    period_data = []
    for dates in dividend_dates:

        if not dividend_years[counter][0] == dividend_years[counter][1]:
            time_series_data_y1 = get_time_series(symbol, dividend_years[counter][0])
            time_series_data_y2 = get_time_series(symbol, dividend_years[counter][1])
            period_data_y1 = get_time_series_period_df(time_series_data_y1, ymd_to_mdyy(dates[0]), ymd_to_mdyy(dates[1]))
            period_data_y2 = get_time_series_period_df(time_series_data_y2, ymd_to_mdyy(dates[0]), ymd_to_mdyy(dates[1]))
            period_data.append(stitch(period_data_y1, period_data_y2))
        else:
            time_series_data = get_time_series(symbol, dividend_years[counter][0])
            period_data_y1 = get_time_series_period_df(time_series_data, ymd_to_mdyy(dates[0]), ymd_to_mdyy(dates[1]))
            period_data.append(period_data_y1)
        counter += 1
    
    print(period_data)

def convert_to_jan_first(dividend_dates):
    dividend_years = []
    for dates in dividend_dates:
        start = dates[0][:4]+ "-01-01"
        end = dates[1][:4]+ "-01-01"
        dividend_years.append((start, end))
    
    return dividend_years
 
# YYYY-MM-DD  ->  M/D/YY          (e.g. 2025-05-01 -> 5/1/25)
def ymd_to_mdyy(date_str):
    month = date_str[5:7].lstrip("0")          # '05' -> '5'
    day   = date_str[8:10].lstrip("0")         # '01' -> '1'
    year  = date_str[2:4]                      # '2025' -> '25'
    return f"{month}/{day}/{year}"

#stock = "AAPL"
#test_period(stock)
