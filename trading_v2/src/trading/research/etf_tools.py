# Shared helpers for the ETF / VIX hypothesis notebooks (H66+). IBKR daily data from scripts/ibkr_download.py.
import os
import numpy as np
import pandas as pd
import trading.utils.constants as constants
from trading.research.fx_hypothesis_tools import monthly_rates


def load_ibkr_daily(names, years):
    # month-end safe: returns a DataFrame of daily closes, one column per name (missing names are listed)
    close = {}
    for name in names:
        yearly = []
        for year in years:
            path = os.path.join(constants.RAW_DATA_DIR, "ibkr", name, str(year), "D", "merged", f"{name}_{year}.csv")
            if os.path.exists(path):
                df = pd.read_csv(path, index_col=0, parse_dates=True)
                if len(df):
                    yearly.append(df["MidClose"])
        if not yearly:
            print(f"{name}: no data, skipped")
            continue
        s = pd.concat(yearly).sort_index()
        s.index = pd.to_datetime(s.index).normalize()
        close[name] = s[~s.index.duplicated(keep="last")]
    if not close:
        raise RuntimeError("No IBKR data: run scripts/download_151_data.sh first")
    close = pd.DataFrame(close).ffill(limit=3)
    first = close.apply(lambda c: c.first_valid_index().date())
    print("first day per name:", ", ".join(f"{k} {v}" for k, v in first.items()))
    return close


def month_ends(index):
    return index.to_series().groupby(index.to_period("M")).max().values


def cash_daily(index):
    # US 3-month rate (data/rates/USD.csv) as a daily return, for money not invested
    r = monthly_rates(["USD"])
    if "USD" not in r:
        return pd.Series(0.0, index=index)
    r = r["USD"].reindex(r.index.union(index)).ffill().reindex(index).fillna(0) / 100
    return r / 252


def run_weights(month_weights, daily_ret, cost_side, period, cash=None):
    # weights chosen at a month-end close, held from the next day; costs on the change in weights;
    # any weight not invested (1 - sum) earns cash if given
    w = month_weights.reindex(daily_ret.index).ffill().shift(1)
    gross = (w * daily_ret[w.columns]).sum(axis=1, min_count=1)
    if cash is not None:
        gross = gross + (1 - w.sum(axis=1, min_count=1)) * cash
    turnover = month_weights.fillna(0).diff().abs().sum(axis=1).reindex(daily_ret.index).fillna(0).shift(1).fillna(0)
    return (gross - turnover * cost_side)[period].fillna(0)


def stats(daily, label=""):
    by_year = (1 + daily).groupby(daily.index.year).prod() - 1
    equity = (1 + daily).cumprod()
    return pd.Series({"CAGR %": 100 * (equity.iloc[-1] ** (252 / len(daily)) - 1),
                      "vol %": 100 * daily.std() * np.sqrt(252),
                      "Sharpe": daily.mean() / daily.std() * np.sqrt(252),
                      "max DD %": 100 * (equity / equity.cummax() - 1).min(),
                      "years + %": 100 * (by_year > 0).mean()}, name=label).round(2)


def monthly(daily):
    return (1 + daily).groupby(daily.index.to_period("M")).prod() - 1


def alpha_vs(daily, bench):
    # monthly regression: strategy = alpha + beta * benchmark. Returns alpha (% a year), beta, t of alpha, yearly alphas
    y, x = monthly(daily), monthly(bench).reindex(monthly(daily).index)
    X = np.column_stack([np.ones(len(x)), x.values])
    coef, *_ = np.linalg.lstsq(X, y.values, rcond=None)
    resid = y.values - X @ coef
    se = np.sqrt(resid.var(ddof=2) * np.linalg.inv(X.T @ X)[0, 0])
    per_month = pd.Series(y.values - coef[1] * x.values, index=y.index)
    yearly = per_month.groupby(per_month.index.year).sum()
    return {"alpha %/yr": 1200 * coef[0], "beta": coef[1], "t alpha": coef[0] / se, "yearly": yearly}


def print_checks(checks, t_value, n_tests):
    for k, v in checks.items():
        print(f"   {'yes' if v else 'NO '}  {k}")
    print(f"   (luck-proof bar for {n_tests} ideas: t > 3.0: {'met' if t_value > 3 else 'not met'})")
    print("   =>", "PASS" if all(checks.values()) else "FAIL")


def alpha_checks(base, spy, beats, n_tests, sharpe_rivals):
    # pass rules for strategies judged on risk-adjusted return: alpha vs SPY, plus Sharpe above every rival
    a = alpha_vs(base, spy)
    yearly = a["yearly"]
    print(f"alpha vs SPY {a['alpha %/yr']:.2f}% a year, beta {a['beta']:.2f}, t {a['t alpha']:.2f}; "
          f"beats {beats:.0f}% of random runs")
    checks = {"alpha t > 2": a["t alpha"] > 2,
              "alpha positive in 60%+ of years": (yearly > 0).mean() >= 0.6,
              "alpha positive without the best year": yearly.drop(yearly.idxmax()).mean() > 0,
              "Sharpe above " + ", ".join(sharpe_rivals): stats(base)["Sharpe"] > max(stats(v)["Sharpe"] for v in sharpe_rivals.values()),
              "beats 95% of random runs": beats >= 95}
    print_checks(checks, a["t alpha"], n_tests)
    return yearly


def relative_checks(base, bench, beats, n_tests, bench_name):
    # pass rules for a rotation judged against holding everything: monthly excess return over the benchmark
    m = monthly(base) - monthly(bench)
    by_year = (1 + base).groupby(base.index.year).prod() - (1 + bench).groupby(bench.index.year).prod()
    t = m.mean() / m.std() * np.sqrt(len(m))
    print(f"excess over {bench_name}: {100 * m.mean():.2f}% a month, t {t:.2f}, years ahead "
          f"{100 * (by_year > 0).mean():.0f}%, beats {beats:.0f}% of random runs")
    checks = {f"t > 2 vs {bench_name}": t > 2,
              "ahead in 60%+ of years": (by_year > 0).mean() >= 0.6,
              "still ahead without the best year": by_year.drop(by_year.idxmax()).mean() > 0,
              f"Sharpe above {bench_name}": stats(base)["Sharpe"] > stats(bench)["Sharpe"],
              "beats 95% of random runs": beats >= 95}
    print_checks(checks, t, n_tests)
    return by_year


def load_oanda_daily(symbols, years):
    # OANDA daily CFD closes and spreads; commodities/bonds are in the forex folder, indices in indices
    from trading.utils.data_manipulation import preprocess_csv
    close, spread = {}, {}
    for symbol in symbols:
        yearly = []
        for year in years:
            for folder in ["forex", "indices"]:
                path = os.path.join(constants.RAW_DATA_DIR, "oanda", folder, symbol, str(year), "D", "merged",
                                    f"{symbol}_{year}.csv")
                if os.path.exists(path):
                    data_list = preprocess_csv(path)
                    if data_list is not None and len(data_list):
                        yearly.append(data_list[["MidClose", "SpreadClose"]])
                    break
        if not yearly:
            print(f"{symbol}: no data, skipped")
            continue
        df = pd.concat(yearly).sort_index()
        df.index = (pd.to_datetime(df.index) + pd.Timedelta(hours=3)).normalize()   # label each bar with the day it closes
        df = df[~df.index.duplicated(keep="last")]
        df = df[df.index.dayofweek < 5]                                           # drop Sunday stub bars
        close[symbol], spread[symbol] = df.MidClose, df.SpreadClose
    close = pd.DataFrame(close).ffill(limit=3)
    return close, pd.DataFrame(spread).reindex(close.index).ffill(limit=3)
