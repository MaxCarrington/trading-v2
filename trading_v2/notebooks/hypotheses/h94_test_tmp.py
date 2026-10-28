import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import trading.utils.constants as constants
from trading.utils.config import load_config
from trading.utils.data_manipulation import preprocess_csv
from trading.backtesting.risk_metrics import account_metrics

cfg = load_config("analysis/h93_bond_month_end_holdout.yaml")
years = list(range(cfg["start_year"], cfg["end_year"] + 1))

def load_daily(name, source):
    parts = []
    for y in years:
        folder = os.path.join(constants.RAW_DATA_DIR, "ibkr", name) if source == "ibkr" else os.path.join(constants.RAW_DATA_DIR, "oanda", "forex", name)
        path = os.path.join(folder, str(y), "D", "merged", f"{name}_{y}.csv")
        d = preprocess_csv(path)
        parts.append(d["MidClose"])
    c = pd.concat(parts)
    c.index = pd.to_datetime(c.index)
    if source == "oanda":
        c.index = c.index + pd.Timedelta(hours=3)
    c.index = c.index.normalize()
    c = c[c.index.dayofweek < 5]
    c = c[c.index <= cfg["data_end"]]                                  # drop the unfinished month
    return c[~c.index.duplicated(keep="last")].astype(float)


closes = {name: load_daily(name, v["source"]) for name, v in cfg["instruments"].items()}
for name, c in closes.items():
    print(name, len(c), "days", c.index[0].date(), "to", c.index[-1].date(), "| per year:", c.groupby(c.index.year).size().to_dict())

def month_end_trades(c, before):
    rows = []
    for (y, m), g in c.groupby([c.index.year, c.index.month]):
        if len(g) < before + 2:
            continue
        a, b = g.index[-1 - before], g.index[-1]
        rows.append({"month": f"{y}-{m:02d}", "year": y, "entry_date": a.date(), "exit_date": b.date(),
                     "gross %": 100 * (g[b] / g[a] - 1)})
    t = pd.DataFrame(rows)
    t["net %"] = t["gross %"] - cfg["cost_round_trip_%"]
    return t


trades = {name: month_end_trades(c, cfg["days_before"]) for name, c in closes.items()}
monthly = pd.DataFrame({name: t.set_index("month")["net %"] for name, t in trades.items()})
monthly["portfolio"] = monthly[list(trades)].mean(axis=1)            # equal weight
print(monthly.tail())

tt = lambda x: x.mean() / x.std() * np.sqrt(len(x))
year_of = monthly.index.str[:4].astype(int)
rows = {}
for col in monthly.columns:
    x = monthly[col].dropna()
    by_year = x.groupby(year_of[monthly[col].notna()]).sum()
    rows[col] = {"months": len(x), "net % per month": round(x.mean(), 3), "t": round(tt(x), 2), "win %": round(100 * (x > 0).mean(), 1),
                 "years +": f"{(by_year > 0).sum()}/{len(by_year)}", "best year %": round(by_year.max(), 2),
                 "w/o best year % per month": round(x[year_of[monthly[col].notna()] != by_year.idxmax()].mean(), 3)}
print(pd.DataFrame(rows).T, "\n")
p = monthly.portfolio
p_years = p.groupby(year_of).sum()
vb = cfg["validation_bar"]
ok = p.mean() > 0 and tt(p) >= vb["min_t"] and (p_years > 0).sum() >= vb["min_years_positive"]
print(f"HOLDOUT BAR (portfolio): {p.mean():.3f}% a month (> 0), t {tt(p):.2f} (>= {vb['min_t']}), "
      f"{(p_years > 0).sum()}/{len(p_years)} years positive (>= {vb['min_years_positive']})  =>  {'PASS' if ok else 'FAIL'}")
print(f"research 2005-18: {cfg['research_reference']}")

print(monthly.groupby(year_of).sum().round(2))

acct = p / 100
acct.index = pd.PeriodIndex(acct.index, freq="M").to_timestamp("M")
eq = (1 + acct).cumprod()
print(pd.Series(account_metrics(acct, 12)).round(2).to_string())
print("max drawdown %:", round(100 * (eq / eq.cummax() - 1).min(), 2), "| worst month %:", round(100 * acct.min(), 2))
fig, ax = plt.subplots(2, 1, figsize=(11, 6), sharex=True)
ax[0].plot(eq); ax[0].set_title("bond month-end portfolio, holdout 2023-26 (1x)")
ax[1].plot(100 * (eq / eq.cummax() - 1)); ax[1].set_title("drawdown %")
plt.tight_layout()
print(plt.show())

print("PASS -> paper trade it (UCITS bond ETFs, market-on-close orders)" if ok else "FAIL -> dead, no changes")

