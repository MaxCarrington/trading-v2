# This is a test file to get the data between an announcement date and a payment date for dividends

# JSON format:
# symbol: This is the stock ticker.
# ex_dividend_date: The date by which you must own the stock to receive the dividend. If you buy the stock on or after this date, you won’t get the dividend.
# declaration_date: The date the company announces the dividend and its amount.
# record_date: The company looks at its shareholder records on this date to determine who gets the dividend.
# payment_date: The date the dividend is actually paid out to shareholders.
# amount: The cash amount paid per share—in this case, $ USD per share.


from trading.utils.paths import get_time_series_file_path, get_time_series_period_df, stitch_dataframes# return format: [(declaration date, payment date)]
#from trading.data.dividends import get_dividend_dates

# Gets all time series data from the period between dividend declaration date and payment date 
def test_period(symbol):
    dividend_dates = get_dividend_dates(symbol)
    dividend_years = convert_to_jan_first(dividend_dates)

    counter = 0

    period_data = []
    for dates in dividend_dates:

        if not dividend_years[counter][0] == dividend_years[counter][1]:
            time_series_data_y1 = get_time_series_file_path(symbol, dividend_years[counter][0])
            time_series_data_y2 = get_time_series_file_path(symbol, dividend_years[counter][1])
            period_data_y1 = get_time_series_period_df(time_series_data_y1, ymd_to_mdyy(dates[0]), ymd_to_mdyy(dates[1]))
            period_data_y2 = get_time_series_period_df(time_series_data_y2, ymd_to_mdyy(dates[0]), ymd_to_mdyy(dates[1]))
            period_data.append(stitch_dataframes(period_data_y1, period_data_y2))
        else:
            time_series_data = get_time_series_file_path(symbol, dividend_years[counter][0])
            period_data_y1 = get_time_series_period_df(time_series_data, ymd_to_mdyy(dates[0]), ymd_to_mdyy(dates[1]))
            period_data.append(period_data_y1)
        counter += 1
    
    print(period_data)

# Convert dividend dates to (YYYY-01-01, YYYY-01-01) format for time series file lookup
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
