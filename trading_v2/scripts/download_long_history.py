# Downloads long daily history for the month-end stocks vs bonds test (data OANDA does not have before 2005).
#   S&P 500 index (^GSPC) and SPY/TLT ETFs from Yahoo (falls back to Stooq), 10y and 30y Treasury yields from FRED.
# Run once from the repo folder:  pip install -U yfinance  then  python scripts/download_long_history.py
# Already-downloaded files are skipped, so after a "rate limited" error just run it again later.
import os
import time
import pandas as pd

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "long_history")
os.makedirs(OUT, exist_ok=True)


def from_yahoo(ticker):
    import yfinance as yf
    for attempt in range(4):
        df = yf.download(ticker, start="1960-01-01", end="2026-10-20", auto_adjust=False, progress=False)
        if len(df):
            df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]   # flatten yfinance columns
            return df
        print(f"  Yahoo gave nothing for {ticker}, waiting {30 * (attempt + 1)}s and trying again")
        time.sleep(30 * (attempt + 1))
    return pd.DataFrame()


def from_stooq(ticker):
    # Stooq's free CSV download (^spx = S&P 500 index, spy.us / tlt.us = ETFs)
    code = {"^GSPC": "^spx", "SPY": "spy.us", "TLT": "tlt.us"}[ticker]
    try:
        df = pd.read_csv(f"https://stooq.com/q/d/l/?s={code}&i=d", index_col="Date", parse_dates=True)
        return df if "Close" in df.columns else pd.DataFrame()
    except Exception as e:
        print(f"  Stooq failed for {ticker}: {e}")
        return pd.DataFrame()


for ticker, name in [("^GSPC", "GSPC"), ("SPY", "SPY"), ("TLT", "TLT")]:
    path = os.path.join(OUT, f"{name}.csv")
    if os.path.exists(path) and len(pd.read_csv(path)) > 0:
        print(name, "already downloaded, skipping")
        continue
    df = from_yahoo(ticker)
    if df.empty:
        print(f"  trying Stooq for {ticker}")
        df = from_stooq(ticker)
    if df.empty:
        print(f"{name}: FAILED, run the script again later")
        continue
    df.to_csv(path)
    print(name, len(df), "rows from", df.index[0].date())
    time.sleep(5)   # be gentle with Yahoo

for series in ["DGS10", "DGS30"]:
    path = os.path.join(OUT, f"{series}.csv")
    if os.path.exists(path):
        print(series, "already downloaded, skipping")
        continue
    df = pd.read_csv(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}")
    df.to_csv(path, index=False)
    print(series, len(df), "rows from", df.iloc[0, 0])
