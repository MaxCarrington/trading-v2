# Quick test: downloads forex bars from Interactive Brokers (through IB Gateway) and prints them.
#   PYTHONPATH=src python scripts/ibkr_forex_test.py
# Read-only: it never places orders. Change the settings below to try other pairs or bar sizes.
import os
import pandas as pd
from ib_async import IB, Forex, util
import trading.utils.constants as constants

PAIRS = ["EURUSD", "GBPUSD", "USDJPY"]
DURATION = "1 M"          # how far back: "1 W", "1 M", "1 Y" ...
BAR_SIZE = "1 hour"       # "1 day", "1 hour", "5 mins" ...
PORT = 4002               # IB Gateway paper account

ib = IB()
ib.connect("127.0.0.1", PORT, clientId=12, readonly=True)
spreads = {}
for pair in PAIRS:
    contract = Forex(pair)
    ib.qualifyContracts(contract)
    got = {}
    for what in ["MIDPOINT", "BID", "ASK"]:
        bars = ib.reqHistoricalData(contract, endDateTime="", durationStr=DURATION, barSizeSetting=BAR_SIZE,
                                    whatToShow=what, useRTH=False, formatDate=2)
        df = util.df(bars)
        if df is None or df.empty:
            print(f"{pair} {what}: no data (see the error above)")
            continue
        print(f"{pair} {what}: {len(df)} bars from {df.date.iloc[0]} to {df.date.iloc[-1]}")
        got[what] = df.set_index("date")
        if what == "MIDPOINT":
            print(df[["date", "open", "high", "low", "close"]].tail(3).to_string(index=False))
            folder = os.path.join(constants.RAW_DATA_DIR, "ibkr", "test")
            os.makedirs(folder, exist_ok=True)
            df.to_csv(os.path.join(folder, f"{pair}_{BAR_SIZE.replace(' ', '')}.csv"), index=False)
    if "BID" in got and "ASK" in got:
        # spread at the end of each bar, in pips (0.01 for JPY pairs, 0.0001 otherwise)
        pip = 0.01 if "JPY" in pair else 0.0001
        spread = (got["ASK"]["close"] - got["BID"]["close"]) / pip
        spreads[pair] = spread.groupby(spread.index.tz_convert("America/New_York").hour).median()
ib.disconnect()

# median spread in pips by New York hour (the month-end bot trades at 16:30 New York)
table = pd.DataFrame(spreads).round(2)
table.index.name = "NY hour"
print("\nMedian spread in pips by New York hour:")
print(table.to_string())
print("\nMedian over all hours:", table.median().round(2).to_dict())
