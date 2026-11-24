# Parameter grid for the month-end stocks vs bonds trade on the RESEARCH period only (default 2005-2018),
# all three markets, capital split 1/3 each. Same trade logic as scripts/month_end_stocks_bonds.py (no baselines, no
# dashboard, so it is fast). Output: results/month_end_stocks_bonds/grid_<start>_<end>.csv, one row per setting.
#   python scripts/month_end_grid.py 2005 2018 [sizing,sizing,...]
import os
import sys
import itertools
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
START, END = int(sys.argv[1]), int(sys.argv[2])
SIZINGS = sys.argv[3].split(",") if len(sys.argv) > 3 else ["none", "vol", "gap"]
MARKETS = [("SPX500_USD", "USB30Y_USD"), ("DE30_EUR", "DE10YB_EUR"), ("UK100_GBP", "UK10YB_GBP")]
THRESHOLDS = [0.01, 0.015, 0.02, 0.025, 0.03, 0.04, 0.05]
DAYS_BEFORE = [2, 3, 4, 5, 6]
DAYS_AFTER = [1, 2, 3, 4, 5]
COMMISSION_PCT, TARGET_VOL, MAX_SIZE = 0.03, 0.15, 1.5


def load_oanda_close(pair):
    frames = []
    for y in range(START - 1, END + 2):
        for folder in ["forex", "indices"]:
            f = f"{ROOT}/data/raw/oanda/{folder}/{pair}/{y}/D/merged/{pair}_{y}.csv"
            if os.path.exists(f):
                frames.append(pd.read_csv(f, usecols=["Time", "MidClose"]))
                break
    df = pd.concat(frames)
    df["date"] = (pd.to_datetime(df["Time"]) + pd.Timedelta(hours=3)).dt.normalize()
    return df.drop_duplicates("date").set_index("date")["MidClose"]


def prepare(stock_name, bond_name):
    px = pd.concat({"stock": load_oanda_close(stock_name), "bond": load_oanda_close(bond_name)}, axis=1).dropna()
    px = px[px.index.dayofweek < 5]
    ret = px.stock.pct_change()
    days = px.index[(px.index.year >= START) & (px.index.year <= END)]
    return dict(px=px, ret=ret, vol20=ret.rolling(20).std() * np.sqrt(252), days=days,
                groups=list(px.groupby(px.index.to_period("M"))), pos={d: k for k, d in enumerate(days)})


def run(m, thr, db, da, sizing):
    px, groups, days, pos = m["px"], m["groups"], m["days"], m["pos"]
    profits, daily = [], np.zeros(len(days))
    ret = m["ret"].reindex(days).values
    for i in range(1, len(groups) - 1):
        prev, (per, cur), nxt = groups[i - 1][1], groups[i], groups[i + 1][1]
        if per.year < START or per.year > END or len(cur) <= db or len(nxt) < da:
            continue
        base, sig = prev.iloc[-1], cur.iloc[-1 - db]
        gap = (sig.stock / base.stock - 1) - (sig.bond / base.bond - 1)
        if gap <= -thr:
            e, x = cur.index[-1 - db], cur.index[-1]
        elif gap >= thr:
            e, x = cur.index[-1], nxt.index[da - 1]
        else:
            continue
        size = min(MAX_SIZE, TARGET_VOL / m["vol20"][e]) if sizing == "vol" else \
            min(MAX_SIZE, abs(gap) / 0.04) if sizing == "gap" else 1.0
        profits.append(size * (100 * (px.stock[x] / px.stock[e] - 1) - 2 * COMMISSION_PCT))
        if e in pos and x in pos:
            daily[pos[e] + 1: pos[x] + 1] = size * ret[pos[e] + 1: pos[x] + 1]
            daily[pos[e]] -= size * COMMISSION_PCT / 100
            daily[pos[x]] -= size * COMMISSION_PCT / 100
    return np.array(profits), pd.Series(daily, index=days)


markets = {s: prepare(s, b) for s, b in MARKETS}
rows = []
for sizing, thr, db, da in itertools.product(SIZINGS, THRESHOLDS, DAYS_BEFORE, DAYS_AFTER):
    row = dict(sizing=sizing, threshold=thr, days_before=db, days_after=da)
    dailies, allp = [], []
    for s, m in markets.items():
        p, d = run(m, thr, db, da, sizing)
        row[f"{s}_t"] = p.mean() / p.std() * len(p) ** .5 if len(p) > 2 else np.nan
        dailies.append(d)
        allp.append(p)
    combined = pd.concat(dailies, axis=1).fillna(0).mean(axis=1)
    p = np.concatenate(allp)
    eq = (1 + combined).cumprod()
    yrs = (1 + combined).groupby(combined.index.year).prod() - 1
    row.update(trades=len(p), pct_per_trade=p.mean(), t=p.mean() / p.std() * len(p) ** .5,
               sharpe=combined.mean() / combined.std() * np.sqrt(252), cagr=100 * (eq.iloc[-1] ** (252 / len(eq)) - 1),
               max_dd=100 * (eq / eq.cummax() - 1).min(), years_pos=int((yrs > 0).sum()), n_years=len(yrs))
    rows.append(row)
out = f"{ROOT}/results/month_end_stocks_bonds"
os.makedirs(out, exist_ok=True)
path = f"{out}/grid_{START}_{END}_{'_'.join(SIZINGS)}.csv"
pd.DataFrame(rows).round(3).to_csv(path, index=False)
print("saved", path, len(rows), "settings")
