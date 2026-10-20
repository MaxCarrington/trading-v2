# H16 "gap calendar": a second strategy for the days the month-end trade leaves the money idle.
# Rules written down BEFORE the first run (2026-10-20), from what the earlier tests taught us:
#   - only structural, calendar-driven effects (flows/positioning), no price patterns, no parameters to tune
#   - long stocks only, short holds, cheap ETF costs (0.03% per side), no stops
#   - never overlaps the month-end stocks vs bonds trade (that trade has priority)
# Two documented effects:
#   A. pre-FOMC drift: buy at the close of the trading day before an FOMC announcement, sell at the close of
#      the announcement day (Lucca & Moench 2015). Dates: data/fomc_dates.csv (2005 onwards only).
#   B. pre-holiday: buy at the close two trading days before an NYSE holiday, sell at the close of the last
#      trading day before the holiday.
# Pass rules as always: mean > 0, t > 2, 60%+ of years positive, positive without the best year, beats random.
#   python scripts/gap_calendar.py --start 2005 --end 2018                       (SPX500 from OANDA)
#   python scripts/gap_calendar.py --source long --start 1993 --end 2004         (SPY; pre-holiday only, no FOMC dates)
import os
import sys
import argparse
import numpy as np
import pandas as pd
from pandas.tseries.holiday import (AbstractHolidayCalendar, Holiday, GoodFriday, USMartinLutherKingJr,
                                    USPresidentsDay, USMemorialDay, USLaborDay, USThanksgivingDay, nearest_workday)

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))
from trading.backtesting.risk_metrics import account_metrics

parser = argparse.ArgumentParser()
parser.add_argument("--start", type=int, default=2005)
parser.add_argument("--end", type=int, default=2018)
parser.add_argument("--source", choices=["oanda", "long"], default="oanda")
parser.add_argument("--commission_pct", type=float, default=0.03)
args = parser.parse_args()


class NYSECalendar(AbstractHolidayCalendar):
    rules = [
        Holiday("NewYearsDay", month=1, day=1, observance=nearest_workday),
        USMartinLutherKingJr, USPresidentsDay, GoodFriday, USMemorialDay,
        Holiday("Juneteenth", month=6, day=19, start_date="2022-01-01", observance=nearest_workday),
        Holiday("IndependenceDay", month=7, day=4, observance=nearest_workday),
        USLaborDay, USThanksgivingDay,
        Holiday("Christmas", month=12, day=25, observance=nearest_workday),
    ]


def load(pair):
    if args.source == "long":
        df = pd.read_csv(f"{ROOT}/data/long_history/{pair}.csv", index_col=0, parse_dates=True)
        return pd.to_numeric(df["Close"], errors="coerce").dropna()
    frames = []
    for y in range(args.start - 1, args.end + 2):
        for folder in ["forex", "indices"]:
            f = f"{ROOT}/data/raw/oanda/{folder}/{pair}/{y}/D/merged/{pair}_{y}.csv"
            if os.path.exists(f):
                frames.append(pd.read_csv(f, usecols=["Time", "MidClose"]))
                break
    df = pd.concat(frames)
    df["date"] = (pd.to_datetime(df["Time"]) + pd.Timedelta(hours=3)).dt.normalize()
    return df.drop_duplicates("date").set_index("date")["MidClose"]


if args.source == "long":
    stock, bond = load("SPY"), None
    y = pd.read_csv(f"{ROOT}/data/long_history/DGS30.csv")
    yy = pd.to_numeric(y.iloc[:, 1], errors="coerce"); yy.index = pd.to_datetime(y.iloc[:, 0]); yy = yy.dropna() / 100
    dur = (1 - (1 + yy / 2) ** (-2 * 30)) / yy
    bond = (1 + (yy.shift() / 252 - dur.shift() * yy.diff()).fillna(0)).cumprod()
else:
    stock, bond = load("SPX500_USD"), load("USB30Y_USD")
holidays = NYSECalendar().holidays("1990-01-01", "2027-12-31")
px = pd.concat({"stock": stock, "bond": bond}, axis=1).dropna()
px = px[(px.index.dayofweek < 5) & ~px.index.isin(holidays)]          # NYSE trading days only
days = px.index
pos = {d: k for k, d in enumerate(days)}

# month-end trade windows (same frozen rule), so this strategy never overlaps it
busy = set()
groups = list(px.groupby(days.to_period("M")))
for i in range(1, len(groups) - 1):
    prev, cur, nxt = groups[i - 1][1], groups[i][1], groups[i + 1][1]
    if len(cur) <= 4 or len(nxt) < 3:
        continue
    gap = (cur.stock.iloc[-5] / prev.stock.iloc[-1] - 1) - (cur.bond.iloc[-5] / prev.bond.iloc[-1] - 1)
    if gap <= -0.02:
        busy.update(cur.index[-4:])
    elif gap >= 0.02:
        busy.update(nxt.index[:3])

trades = []
def add(exit_day, kind):
    if exit_day not in pos or pos[exit_day] == 0 or exit_day in busy:
        return
    if not (args.start <= exit_day.year <= args.end):
        return
    entry_day = days[pos[exit_day] - 1]
    gross = 100 * (px.stock[exit_day] / px.stock[entry_day] - 1)
    trades.append(dict(entry_date=entry_day, exit_date=exit_day, kind=kind, gross_pct=gross,
                       profit=gross - 2 * args.commission_pct))

for h in holidays:                       # B. pre-holiday: hold the last trading day before each holiday
    before = days[days < h]
    if len(before):
        add(before[-1], "pre_holiday")
if args.source == "oanda":               # A. pre-FOMC: hold the announcement day
    for d in pd.to_datetime(pd.read_csv(f"{ROOT}/data/fomc_dates.csv")["date"]):
        add(d, "pre_fomc")
t = pd.DataFrame(trades).drop_duplicates("exit_date").sort_values("exit_date").reset_index(drop=True)


def stats(p):
    return f"{len(p)} trades, {p.mean():+.3f}%/trade, t {p.mean() / p.std() * len(p) ** .5:.2f}, win {100 * (p > 0).mean():.0f}%"


print(f"== Gap calendar ({'SPY' if args.source == 'long' else 'SPX500'}) {args.start}-{args.end}")
print("ALL:", stats(t.profit), f"| gross {t.gross_pct.mean():+.3f}%")
for k, g in t.groupby("kind"):
    print(f"  {k}:", stats(g.profit))
yrs = t.groupby(t.exit_date.dt.year).profit.sum()
best = yrs.idxmax()
print("years (sum %):", yrs.round(2).to_dict())
print(f"years+ {(yrs > 0).sum()}/{len(yrs)}; without best year {best}: {t[t.exit_date.dt.year != best].profit.mean():+.3f}%/trade")
span = days[(days.year >= args.start) & (days.year <= args.end)]
daily = pd.Series(0.0, index=span)
for _, tr in t.iterrows():
    daily[tr.exit_date] = tr.profit / 100
print("account:", {k: round(float(v), 2) for k, v in account_metrics(daily, 252, 100 * (t.profit > 0).mean()).items()})
r1 = (px.stock.pct_change() * 100 - 2 * args.commission_pct).reindex(span).dropna()
free = r1[~r1.index.isin(busy)]
print(f"baseline: any 1-day hold outside month-end windows {free.mean():+.3f}%/day")
rng = np.random.default_rng(0)
means = [rng.choice(free.values, len(t)).mean() for _ in range(1000)]
print(f"random baseline mean {np.mean(means):+.3f}%; strategy beats {100 * (np.array(means) < t.profit.mean()).mean():.0f}% of random runs")
