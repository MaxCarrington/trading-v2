# Shared helpers for the FX hypothesis notebooks (notebooks/hypotheses/idle_cash/*.ipynb).
# Every notebook uses the same loading, costs, swap and pass rules, so results can be compared.
#
#   load_daily(symbols, years)      -> {symbol: DataFrame of daily Mid OHLC + SpreadClose}, dated by the day the bar closes
#   load_hourly(symbol, years)      -> DataFrame of H1 bars, index in UTC, plus a "london" column (Europe/London time)
#   spread_pips(symbol)             -> typical OANDA spread in pips today (median H1 spread 07:00-17:00 London, 2016-18)
#   finish_trades(trades, cfg)      -> adds gross, cost, swap and net pips to a trades table
#   summary(trades)                 -> one row: trades, mean, t, win %, years positive, mean without best year
#   pass_rules(trades, ...)         -> prints PASS / FAIL against the usual rules
#   random_baseline(trades, daily)  -> % of random-entry runs (same pair, side, hold length) the strategy beats
#   in_idle_window(dates)           -> True when the date is outside the month-end strategy's holding windows
import os
import numpy as np
import pandas as pd
import trading.utils.constants as constants
from trading.utils.data_manipulation import preprocess_csv

FOREX_DIR = constants.OANDA_FOREX_DATA_DIR
RATES_DIR = os.path.join(constants.DATA_DIR, "rates")
MERGED = "merged"

# used when a pair has no H1 data to measure its spread from (pips, OANDA retail, my estimate)
FALLBACK_SPREAD = {"EUR_USD": 1.0, "GBP_USD": 1.5, "USD_JPY": 1.0, "AUD_USD": 1.2, "NZD_USD": 1.8, "USD_CAD": 1.8,
                   "USD_CHF": 1.6, "EUR_JPY": 1.6, "GBP_JPY": 2.8, "AUD_JPY": 1.8, "EUR_GBP": 1.4, "EUR_CHF": 1.8,
                   "EUR_AUD": 2.6, "AUD_NZD": 2.6, "NZD_JPY": 2.4, "CAD_JPY": 2.4, "CHF_JPY": 2.6}
_spread_cache = {}


def pip_size(symbol):
    return 0.01 if "JPY" in symbol else 0.0001


def _year_file(symbol, year, timeframe):
    return os.path.join(FOREX_DIR, symbol, str(year), timeframe, MERGED, f"{symbol}_{year}.csv")


def load_daily(symbols, years):
    out = {}
    for symbol in symbols:
        yearly = []
        for year in years:
            path = _year_file(symbol, year, "D")
            if os.path.exists(path):
                data_list = preprocess_csv(path)
                if data_list is not None:
                    yearly.append(data_list[["MidOpen", "MidHigh", "MidLow", "MidClose", "SpreadClose"]])
        if not yearly:
            print(f"no daily data for {symbol}")
            continue
        df = pd.concat(yearly).sort_index()
        df.index = (df.index + pd.Timedelta(hours=3)).normalize()   # label each daily bar with the day it closes
        df = df[~df.index.duplicated(keep="last")]                  # some year files overlap by a day
        df = df[df.index.dayofweek < 5]                             # drop the odd Sunday stub bar
        df = df[df.index.year.isin(years)]
        out[symbol] = df
    return out


def load_hourly(symbol, years):
    yearly = []
    for year in years:
        path = _year_file(symbol, year, "H1")
        if os.path.exists(path):
            data_list = preprocess_csv(path)
            if data_list is not None:
                yearly.append(data_list[["MidOpen", "MidHigh", "MidLow", "MidClose", "SpreadClose"]])
    if not yearly:
        print(f"no hourly data for {symbol}")
        return None
    df = pd.concat(yearly).sort_index()
    df = df[~df.index.duplicated(keep="last")]
    df["london"] = df.index.tz_localize("UTC").tz_convert("Europe/London").tz_localize(None)
    return df


def spread_pips(symbol, years=(2016, 2017, 2018)):
    # Typical spread during London/New York hours, measured from OANDA's own H1 bars.
    # The same (recent) spread is charged in every year: OANDA's 2005-08 spreads were 3-4x wider than now,
    # and the question is whether the idea pays at today's costs. Only costs use these years, not signals.
    key = (symbol, tuple(years))
    if key not in _spread_cache:
        values = []
        for year in years:
            path = _year_file(symbol, year, "H1")
            if os.path.exists(path):
                h = pd.read_csv(path, usecols=["Time", "SpreadClose"])
                hours = pd.to_datetime(h["Time"], utc=True).dt.tz_convert("Europe/London").dt.hour
                values.append(h.loc[(hours >= 7) & (hours < 17), "SpreadClose"].median() / pip_size(symbol))
        value = float(np.median(values)) if values else None
        if value is None or not np.isfinite(value):
            value = FALLBACK_SPREAD.get(symbol, 2.0)
        _spread_cache[key] = float(value)
    return _spread_cache[key]


def monthly_rates(currencies):
    # FRED 3-month rates (% a year). Each month's rate is only used from the month after (published late).
    rates = {}
    for ccy in currencies:
        path = os.path.join(RATES_DIR, f"{ccy}.csv")
        if os.path.exists(path):
            r = pd.read_csv(path, index_col=0, parse_dates=True).iloc[:, 0]
            r.index = r.index + pd.DateOffset(months=1)
            rates[ccy] = r
    return pd.DataFrame(rates)


def rate_on(rates, ccy, date):
    if ccy not in rates:
        return 0.0
    r = rates[ccy].loc[:date].dropna()
    return float(r.iloc[-1]) if len(r) else 0.0


def finish_trades(trades, cfg):
    # trades needs: symbol, entry_date, exit_date, direction (+1 long, -1 short), entry, exit
    # cfg needs: slippage_pips (per side) and swap_markup_% (OANDA financing markup, % a year)
    t = trades.copy()
    if t.empty:
        for c in ["gross", "cost", "swap", "net", "days", "year"]:
            t[c] = []
        return t
    t["entry_date"] = pd.to_datetime(t["entry_date"])
    t["exit_date"] = pd.to_datetime(t["exit_date"])
    ccys = set(t.symbol.str[:3]) | set(t.symbol.str[4:])
    rates = monthly_rates(ccys)
    pips = t.symbol.map(pip_size)
    t["gross"] = t.direction * (t.exit - t.entry) / pips
    t["cost"] = [spread_pips(s) + 2 * cfg["slippage_pips"] for s in t.symbol]
    t["days"] = (t.exit_date.dt.normalize() - t.entry_date.dt.normalize()).dt.days   # nights held
    swap = []
    for s, d, n, side, price, p in zip(t.symbol, t.entry_date, t.days, t.direction, t.entry, pips):
        if n <= 0:
            swap.append(0.0)
            continue
        gap = side * (rate_on(rates, s[:3], d) - rate_on(rates, s[4:], d)) - cfg["swap_markup_%"]
        swap.append(gap / 100 / 365 * n * price / p)
    t["swap"] = swap
    t["net"] = t.gross - t.cost + t.swap
    t["year"] = t.entry_date.dt.year
    return t.reset_index(drop=True)


def summary(trades, col="net"):
    x = trades[col].dropna()
    n = len(x)
    if n < 2:
        return pd.Series({"trades": n, "mean": x.mean() if n else np.nan, "t": np.nan, "win_%": np.nan,
                          "years_+%": np.nan, "mean_wo_best_year": np.nan})
    by_year = trades.groupby("year")[col].sum()
    best = by_year.idxmax()
    rest = trades.loc[trades.year != best, col]
    return pd.Series({"trades": n, "mean": round(x.mean(), 2), "t": round(x.mean() / x.std() * np.sqrt(n), 2),
                      "win_%": round(100 * (x > 0).mean(), 1), "years_+%": round(100 * (by_year > 0).mean(), 1),
                      "mean_wo_best_year": round(rest.mean(), 2) if len(rest) else np.nan})


def random_baseline(trades, daily, runs=1000, seed=0):
    # Same pair, same side and same number of trading days held, but a random entry day in the same years.
    # Returns the % of random runs whose average GROSS pips the strategy beats (95+ is what we want).
    if trades.empty:
        return np.nan
    rng = np.random.default_rng(seed)
    years = set(trades.year)
    gross_runs = np.zeros(runs)
    for s, grp in trades.groupby("symbol"):
        px = daily[s]["MidClose"]
        px = px[px.index.year.isin(years)]
        idx = px.index
        holds = np.array([max(1, ((idx > a) & (idx <= b)).sum()) for a, b in zip(grp.entry_date, grp.exit_date)])
        sides = grp.direction.values
        values = px.values
        for r in range(runs):
            starts = rng.integers(0, len(values) - holds.max() - 1, len(holds))
            moves = sides * (values[starts + holds] - values[starts]) / pip_size(s)
            gross_runs[r] += moves.sum()
    gross_runs /= len(trades)
    return round(100 * (trades.gross.mean() > gross_runs).mean(), 1)


def pass_rules(trades, daily=None, label="", t_min=2.0, n_tests=1):
    # Usual rules: net t > 2, 60%+ of years positive, still positive without the best year, beats random entry.
    # n_tests: how many ideas were tried in this batch. With many tries, t > 2 happens by luck about 1 in 40 times
    # each, so a Bonferroni-style bar is also printed for information.
    s = summary(trades)
    rb = random_baseline(trades, daily) if daily is not None else np.nan
    checks = {"mean > 0": s["mean"] > 0, f"t > {t_min}": s["t"] > t_min, "60%+ years positive": s["years_+%"] >= 60,
              "positive without best year": s["mean_wo_best_year"] > 0}
    if daily is not None:
        checks["beats 95% of random entries (gross)"] = rb >= 95
    ok = all(bool(v) for v in checks.values()) and s["trades"] >= 30
    print(f"{label}: {int(s['trades'])} trades, net {s['mean']} pips/trade, t {s['t']}, years + {s['years_+%']}%, "
          f"without best year {s['mean_wo_best_year']}, beats random {rb}%")
    for k, v in checks.items():
        print(f"   {'yes' if v else 'NO '}  {k}")
    if s["trades"] < 30:
        print("   NO   at least 30 trades")
    if n_tests > 1:
        from math import erf, sqrt
        # one-sided bar so that the chance of any of n_tests passing by luck is about 5%
        target = 0.05 / n_tests
        z = 1.645
        while 0.5 * (1 - erf(z / sqrt(2))) > target:
            z += 0.01
        print(f"   (for {n_tests} ideas tested, a luck-proof bar would be t > {z:.2f}: "
              f"{'met' if s['t'] > z else 'not met'})")
    print("   =>", "PASS" if ok else "FAIL")
    return {"label": label, **s.to_dict(), "beats_random_%": rb, "pass": ok}


def business_days(year, month):
    start = pd.Timestamp(year, month, 1)
    return pd.bdate_range(start, start + pd.offsets.MonthEnd(0))


def in_idle_window(dates, first=4, last_gap=5):
    # The month-end strategy can hold an index from 4 trading days before the last trading day until the 3rd
    # trading day of the next month. "Idle" = trading day `first` of the month up to `last_gap` days before the last.
    out = []
    for d in pd.to_datetime(pd.Series(dates)):
        days = business_days(d.year, d.month)
        pos = days.searchsorted(d.normalize())
        out.append(first - 1 <= pos <= len(days) - 1 - last_gap)
    return np.array(out, dtype=bool)


def yearly_table(trades, col="net"):
    return trades.groupby("year")[col].agg(["count", "mean", "sum"]).round(2)


def plot_results(trades, title, col="net"):
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(13, 3.5))
    t = trades.sort_values("exit_date")
    axes[0].plot(t.exit_date, t[col].cumsum(), label="net")
    axes[0].plot(t.exit_date, t["gross"].cumsum(), label="gross", alpha=0.6)
    axes[0].axhline(0, color="grey", lw=0.5)
    axes[0].set_title(f"{title}: cumulative pips")
    axes[0].legend()
    yearly = t.groupby("year")[col].sum()
    axes[1].bar(yearly.index, yearly.values, color=["tab:green" if v > 0 else "tab:red" for v in yearly.values])
    axes[1].set_title("net pips per year")
    plt.tight_layout()
    plt.show()
