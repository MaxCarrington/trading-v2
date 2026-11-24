# Downloads historical bars from Interactive Brokers (through IB Gateway) into data/raw/ibkr/,
# in the same layout and columns as the OANDA files, so the notebooks can read them.
#   PYTHONPATH=src python scripts/ibkr_download.py                                  (uses configs/data/ibkr_download.yaml)
#   PYTHONPATH=src python scripts/ibkr_download.py data/ibkr_download_151.yaml      (any other config in configs/)
# Read-only: this script never places orders.
import os
import sys
import time
import pandas as pd
from ib_async import IB, Contract, util
import trading.utils.constants as constants
from trading.utils.config import load_config

cfg = load_config(sys.argv[1] if len(sys.argv) > 1 else "data/ibkr_download.yaml")
OUT_DIR = os.path.join(constants.RAW_DATA_DIR, "ibkr")


def get_bars(ib, contract, year, what):
    # one request per year; the current year asks up to now
    end = "" if year >= pd.Timestamp.now().year else f"{year}1231-23:59:59"
    bars = ib.reqHistoricalData(contract, endDateTime=end, durationStr="1 Y", barSizeSetting=cfg["bar_size"],
                                whatToShow=what, useRTH=False, formatDate=2)
    df = util.df(bars)
    if df is None or df.empty:
        return None
    df["Time"] = pd.to_datetime(df["date"], utc=True).dt.tz_localize(None)
    df = df[df.Time.dt.year == year]
    return df.set_index("Time")


def year_table(ib, contract, year, sec_type):
    if sec_type in ["STK", "IND"]:          # shares, ETFs and indices (e.g. VIX) have no bid/ask history
        t = get_bars(ib, contract, year, "TRADES")
        if t is None:
            return None
        out = pd.DataFrame({f"Mid{c.title()}": t[c] for c in ["open", "high", "low", "close"]})
        out["SpreadClose"] = 0.0
        out["Volume"] = t["volume"]
        return out
    bid = get_bars(ib, contract, year, "BID")
    ask = get_bars(ib, contract, year, "ASK")
    if bid is None or ask is None:
        return None
    out = pd.DataFrame(index=bid.index.intersection(ask.index))
    for c in ["open", "high", "low", "close"]:
        out[f"Bid{c.title()}"] = bid[c]
        out[f"Ask{c.title()}"] = ask[c]
    for c in ["Open", "High", "Low", "Close"]:
        out[f"Mid{c}"] = (out[f"Bid{c}"] + out[f"Ask{c}"]) / 2
    out["SpreadClose"] = out["AskClose"] - out["BidClose"]
    out["Volume"] = 0
    return out


def adjusted_table(ib, contract):
    # dividend-adjusted daily prices (total return), for ETFs. IBKR only gives these in one request ending today.
    years = pd.Timestamp.now().year - cfg["start_year"] + 1
    bars = ib.reqHistoricalData(contract, endDateTime="", durationStr=f"{years} Y", barSizeSetting=cfg["bar_size"],
                                whatToShow="ADJUSTED_LAST", useRTH=True, formatDate=2)
    t = util.df(bars)
    if t is None or t.empty:
        return None
    t["Time"] = pd.to_datetime(t["date"]).dt.tz_localize(None)
    t = t.set_index("Time")
    out = pd.DataFrame({f"Mid{c.title()}": t[c] for c in ["open", "high", "low", "close"]})
    out["SpreadClose"] = 0.0
    out["Volume"] = t["volume"]
    return out


def save(name, year, table):
    folder = os.path.join(OUT_DIR, name, str(year), cfg["timeframe"], "merged")
    os.makedirs(folder, exist_ok=True)
    table.to_csv(os.path.join(folder, f"{name}_{year}.csv"))
    print(f"{name} {year}: {len(table)} bars, median spread {table.SpreadClose.median():.4g}")


ib = IB()
ib.connect(cfg["host"], cfg["port"], clientId=cfg["client_id"], readonly=True)
for inst in cfg["instruments"]:
    contract = Contract(secType=inst["sec_type"], symbol=inst["symbol"], exchange=inst["exchange"],
                        currency=inst["currency"], primaryExchange=inst.get("primary_exchange", ""))
    if not ib.qualifyContracts(contract):
        print(f"{inst['name']}: IBKR doesn't recognise this contract, skipped")
        continue
    if inst["sec_type"] == "STK" and cfg.get("adjusted", False):
        # adjusted prices change after every dividend, so all years are rewritten each run
        table = adjusted_table(ib, contract)
        if table is None:
            print(f"{inst['name']}: no data")
            continue
        for year in range(cfg["start_year"], cfg["end_year"] + 1):
            if (table.index.year == year).any():
                save(inst["name"], year, table[table.index.year == year])
        time.sleep(1)
        continue
    for year in range(cfg["start_year"], cfg["end_year"] + 1):
        # a finished year that is already saved is not downloaded again
        if os.path.exists(os.path.join(OUT_DIR, inst["name"], str(year), cfg["timeframe"], "merged",
                                       f"{inst['name']}_{year}.csv")) and year < pd.Timestamp.now().year:
            print(f"{inst['name']} {year}: already downloaded, skipped")
            continue
        table = year_table(ib, contract, year, inst["sec_type"])
        if table is None or table.empty:
            print(f"{inst['name']} {year}: no data")
            continue
        save(inst["name"], year, table)
        time.sleep(1)          # stay well inside IBKR's pacing limits
ib.disconnect()
