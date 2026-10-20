# Month-end stocks vs bonds rebalancing trade (rules fixed BEFORE running, from the r/algotrading post).
# Signal day = 4 trading days before the last trading day of the month.
# gap = stock month-to-date return - bond month-to-date return (from last close of previous month).
#   gap <= -threshold: buy stocks at signal-day close, sell at last close of the month.
#   gap >= +threshold: buy stocks at last close of the month, sell at close of 3rd trading day of next month.
# Costs: commission_pct per side (ETF).
#
# With no options this is the frozen rule tested on SPX500 vs the 30y bond. Extras (all off by default):
#   --europe        EU50, FR40, NL25, ESPIX, CH20 vs the Bund (same split and dashboard as --all)
#   --everything    --all and --europe together, 8 markets
#   --all           S&P 500, Germany and UK together: the account is split equally between them (returns in each
#                   market's own currency, i.e. as if currency-hedged); one dashboard with every market
#   --markets       your own list instead of --all, e.g. SPX500_USD:USB30Y_USD,UK100_GBP:UK10YB_GBP
#                   (a bond ending in _YIELD is built from data/long_history yields, e.g. CH20_CHF:CH10Y_YIELD)
#   --sizing vol    size = target_vol / last 20 days' volatility (capped at --max_size)
#   --sizing gap    size = |gap| / 4% (a 2% gap = 0.5x, 4% = 1x, 6%+ = 1.5x cap)
#   --leverage 1.5  multiplies every size
#   --cash          idle cash earns the 3-month interest rate of the stock's currency (data/rates/)
#   --source long   1990-2004 style history from data/long_history (S&P 500 index + bond built from FRED yields)
# Every run saves trades.csv, equity.csv and dashboard.html to results/month_end_stocks_bonds/<run name>/ (opens in the browser).
#
# Examples (run from the repo folder):
#   python scripts/month_end_stocks_bonds.py --start 2005 --end 2018                                  (frozen SPX rule)
#   python scripts/month_end_stocks_bonds.py --stock DE30_EUR --bond DE10YB_EUR --start 2005 --end 2026
#   python scripts/month_end_stocks_bonds.py --all --start 2005 --end 2026
#   python scripts/month_end_stocks_bonds.py --europe --start 2005 --end 2026
#   python scripts/month_end_stocks_bonds.py --source long --long_stock SPY --bond DGS30 --start 1993 --end 2004
#   python scripts/month_end_stocks_bonds.py --start 2005 --end 2018 --sizing vol --cash
import os
import sys
import argparse
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))
from trading.backtesting.risk_metrics import account_metrics

ALL_MARKETS = "SPX500_USD:USB30Y_USD,DE30_EUR:DE10YB_EUR,UK100_GBP:UK10YB_GBP"
# OANDA has no French, Dutch, Spanish or Swiss bond, so these use the German Bund (a rough stand-in for CH20)
EUROPE_MARKETS = "EU50_EUR:DE10YB_EUR,FR40_EUR:DE10YB_EUR,NL25_EUR:DE10YB_EUR,ESPIX_EUR:DE10YB_EUR,CH20_CHF:DE10YB_EUR"

parser = argparse.ArgumentParser()
parser.add_argument("--stock", default="SPX500_USD")
parser.add_argument("--bond", default="USB30Y_USD")
parser.add_argument("--all", action="store_true")
parser.add_argument("--europe", action="store_true", help="the 5 other European indices vs the Bund")
parser.add_argument("--everything", action="store_true", help="--all plus --europe: 8 markets")
parser.add_argument("--markets", default=None)
parser.add_argument("--start", type=int, default=2005)
parser.add_argument("--end", type=int, default=2018)
parser.add_argument("--source", choices=["oanda", "long"], default="oanda")
parser.add_argument("--long_stock", default="SPY", help="GSPC (S&P 500 index, from 1960s) or SPY (ETF, from 1993)")
parser.add_argument("--threshold", type=float, default=0.02)
parser.add_argument("--days_before", type=int, default=4)
parser.add_argument("--days_after", type=int, default=3)
parser.add_argument("--commission_pct", type=float, default=0.03)
parser.add_argument("--sizing", choices=["none", "vol", "gap"], default="none")
parser.add_argument("--target_vol", type=float, default=0.15)   # 15% a year, about the S&P 500's long-run volatility
parser.add_argument("--max_size", type=float, default=1.5)
parser.add_argument("--leverage", type=float, default=1.0)
parser.add_argument("--cash", action="store_true")
parser.add_argument("--no_dashboard", action="store_true", help="skip dashboard.html (trades.csv and equity.csv are always saved)")
args = parser.parse_args()


# ---------- data ----------

def load_oanda_close(pair):
    frames = []
    for y in range(args.start - 1, args.end + 2):
        for folder in ["forex", "indices"]:
            f = f"{ROOT}/data/raw/oanda/{folder}/{pair}/{y}/D/merged/{pair}_{y}.csv"
            if os.path.exists(f):
                frames.append(pd.read_csv(f, usecols=["Time", "MidClose"]))
                break
    df = pd.concat(frames)
    # OANDA daily bars start 21:00 or 22:00 UTC (summer/winter) the day before; +3h gives the trading date
    df["date"] = (pd.to_datetime(df["Time"]) + pd.Timedelta(hours=3)).dt.normalize()
    return df.drop_duplicates("date").set_index("date")["MidClose"]


def load_long_stock():
    # Close = price only (no dividends), like the OANDA index prices
    df = pd.read_csv(f"{ROOT}/data/long_history/{args.long_stock}.csv", index_col=0, parse_dates=True)
    return pd.to_numeric(df["Close"], errors="coerce").dropna()


def load_long_bond(series, years_to_maturity):
    # no bond ETF before 2002, so build a bond price from daily yields:
    # daily return = interest (yield / 252) - modified duration x change in yield (par bond, semi-annual coupons)
    df = pd.read_csv(f"{ROOT}/data/long_history/{series}.csv")
    y = pd.to_numeric(df.iloc[:, 1], errors="coerce")
    y.index = pd.to_datetime(df.iloc[:, 0])
    y = y.dropna() / 100
    duration = (1 - (1 + y / 2) ** (-2 * years_to_maturity)) / y
    ret = y.shift() / 252 - duration.shift() * y.diff()
    return (1 + ret.fillna(0)).cumprod()


def load_cash_rate(currency, dates):
    # monthly 3-month interest rate in %, used from the month after it is published (no look-ahead)
    df = pd.read_csv(f"{ROOT}/data/rates/{currency}.csv")
    r = pd.Series(pd.to_numeric(df.iloc[:, 1], errors="coerce").values, index=pd.to_datetime(df.iloc[:, 0]))
    r = r.shift(1).reindex(dates, method="ffill")
    return r.fillna(0) / 100


# ---------- one market: trades and daily account ----------

def run_market(stock_name, bond_name):
    if args.source == "long":
        stock, bond, currency = load_long_stock(), load_long_bond(bond_name, 30 if "30" in bond_name else 10), "USD"
    else:
        # a bond name ending in _YIELD (e.g. CH10Y_YIELD) is built from daily yields in data/long_history
        bond = load_long_bond(bond_name[:-6], 30 if "30" in bond_name else 10) if bond_name.endswith("_YIELD") \
            else load_oanda_close(bond_name)
        stock, currency = load_oanda_close(stock_name), stock_name.split("_")[-1]
    px = pd.concat({"stock": stock, "bond": bond}, axis=1).dropna()
    px = px[px.index.dayofweek < 5]
    stock_ret = px.stock.pct_change()
    vol20 = stock_ret.rolling(20).std() * np.sqrt(252)

    def trade_size(gap, entry_day):
        if args.sizing == "vol":
            size = min(args.max_size, args.target_vol / vol20[entry_day])
        elif args.sizing == "gap":
            size = min(args.max_size, abs(gap) / 0.04)
        else:
            size = 1.0
        return size * args.leverage

    groups = list(px.groupby(px.index.to_period("M")))
    trades = []
    for i in range(1, len(groups) - 1):
        prev, (per, cur), nxt = groups[i - 1][1], groups[i], groups[i + 1][1]
        if per.year < args.start or per.year > args.end or len(cur) <= args.days_before:
            continue
        base, sig = prev.iloc[-1], cur.iloc[-1 - args.days_before]
        gap = (sig.stock / base.stock - 1) - (sig.bond / base.bond - 1)
        if gap <= -args.threshold:
            entry_d, exit_d, side = cur.index[-1 - args.days_before], cur.index[-1], "before_month_end"
        elif gap >= args.threshold:
            entry_d, exit_d, side = cur.index[-1], nxt.index[args.days_after - 1], "after_month_end"
        else:
            continue
        size = trade_size(gap, entry_d)
        gross = 100 * (px.stock[exit_d] / px.stock[entry_d] - 1)
        trades.append(dict(entry_date=entry_d, exit_date=exit_d, side=side, gap_pct=100 * gap, size=size,
                           gross_pct=gross, profit=size * (gross - 2 * args.commission_pct)))   # profit = % of account
    t = pd.DataFrame(trades)

    # daily account: in a trade it moves with stocks x size, otherwise cash (0 or interest)
    days = px.index[(px.index.year >= args.start) & (px.index.year <= args.end)]
    cash = load_cash_rate(currency, days) if args.cash else pd.Series(0.0, index=days)
    daily = cash / 252
    in_trade = pd.Series(False, index=days)
    for _, tr in t.iterrows():
        held = days[(days > tr.entry_date) & (days <= tr.exit_date)]
        in_trade[held] = True
        # stocks x size, plus interest on what is not invested (negative = paying to borrow when size > 1)
        daily[held] = tr["size"] * stock_ret[held] + (1 - tr["size"]) * cash[held] / 252
        for d in [tr.entry_date, tr.exit_date]:
            if d in daily.index:
                daily[d] -= tr["size"] * args.commission_pct / 100
    return t, daily, in_trade, px, groups, days


# ---------- report ----------

def stats(p):
    return f"{len(p)} trades, {p.mean():+.3f}%/trade, t {p.mean() / p.std() * len(p) ** .5:.2f}, win {100 * (p > 0).mean():.0f}%"


def report(name, bond_name, t, daily, in_trade, px, groups, days):
    extras = [f"sizing {args.sizing}"] if args.sizing != "none" else []
    extras += [f"leverage {args.leverage}"] if args.leverage != 1 else []
    extras += ["cash interest"] if args.cash else []
    print(f"\n== Month-end {name} vs {bond_name} {args.start}-{args.end}, threshold {args.threshold:.0%} {' '.join(extras)}")
    print("ALL:", stats(t.profit), f"| gross {t.gross_pct.mean():+.3f}% | average size {t['size'].mean():.2f}")
    for s, g in t.groupby("side"):
        print(f"  {s}:", stats(g.profit))
    yrs = t.groupby(t.entry_date.dt.year).profit.sum()
    print("years (sum %):", yrs.round(2).to_dict())
    best = yrs.idxmax()
    print(f"years+ {(yrs > 0).sum()}/{len(yrs)}; without best year {best}: {t[t.entry_date.dt.year != best].profit.mean():+.3f}%/trade")
    for lo, hi in [(2, 3), (3, 5), (5, 100)]:
        g = t[(t.gap_pct.abs() >= lo) & (t.gap_pct.abs() < hi)]
        if len(g) > 1:
            print(f"  gap {lo}-{hi if hi < 100 else '+'}%: {stats(g.profit)}")
    if args.start < 2019 and args.end > 2018:
        for lo, hi, label in [(2005, 2018, "research"), (2019, 2022, "validation"), (2023, 2026, "holdout")]:
            g = t[(t.entry_date.dt.year >= lo) & (t.entry_date.dt.year <= hi)]
            if len(g) > 1:
                print(f"  {label} {lo}-{hi}: {stats(g.profit)}")
    m = account_metrics(daily, 252, win_rate=100 * (t.profit > 0).mean())
    print("account:", {k: round(float(v), 2) for k, v in m.items()})
    print(f"days in a trade: {100 * in_trade.mean():.0f}%")

    # Baseline 1: same windows every month with no signal (does the gap filter add anything?)
    allw = []
    for i in range(1, len(groups) - 1):
        per, cur, nxt = groups[i][0], groups[i][1], groups[i + 1][1]
        if args.start <= per.year <= args.end and len(cur) > args.days_before:
            allw.append((100 * (cur.stock.iloc[-1] / cur.stock.iloc[-1 - args.days_before] - 1),
                         100 * (nxt.stock.iloc[args.days_after - 1] / cur.stock.iloc[-1] - 1)))
    allw = np.array(allw) - 2 * args.commission_pct
    print(f"baseline every month: last-{args.days_before}-days {allw[:, 0].mean():+.3f}%, first-{args.days_after}-days {allw[:, 1].mean():+.3f}%")

    # Baseline 2: random entry days, same number of trades, holding lengths and sizes, 1000 runs
    rng = np.random.default_rng(0)
    pos = {d: k for k, d in enumerate(px.index)}
    holds = [pos[e] - pos[s] for s, e in zip(t.entry_date, t.exit_date)]
    first, last = pos[days[0]], pos[days[-1]] - max(holds)
    means = []
    for _ in range(1000):
        starts = rng.choice(np.arange(first, last), len(holds))
        r = [sz * (100 * (px.stock.iloc[s + h] / px.stock.iloc[s] - 1) - 2 * args.commission_pct)
             for s, h, sz in zip(starts, holds, t["size"])]
        means.append(np.mean(r))
    print(f"random baseline mean {np.mean(means):+.3f}%/trade; strategy beats {100 * (np.array(means) < t.profit.mean()).mean():.0f}% of random runs")


if args.all or args.markets or args.europe or args.everything:
    if args.source == "long":
        sys.exit("--all / --europe / --everything / --markets only work with OANDA data (the long history is S&P 500 only)")
    chosen = args.markets or (f"{ALL_MARKETS},{EUROPE_MARKETS}" if args.everything else EUROPE_MARKETS if args.europe else ALL_MARKETS)
    markets = [m.split(":") for m in chosen.split(",")]
else:
    markets = [(args.long_stock if args.source == "long" else args.stock, args.bond)]

results = {}
for stock_name, bond_name in markets:
    results[stock_name] = run_market(stock_name, bond_name)
    report(stock_name if args.source == "oanda" else f"{args.long_stock} (long history)", bond_name, *results[stock_name])

# Combined account: capital split equally between the markets, each market's daily % return weighted 1/n
n = len(markets)
if n > 1:
    daily_all = pd.concat({k: r[1] for k, r in results.items()}, axis=1).fillna(0)
    combined = daily_all.mean(axis=1)
    t_all = pd.concat([r[0].assign(asset=k) for k, r in results.items()]).sort_values("entry_date")
    m = account_metrics(combined, 252, win_rate=100 * (t_all.profit > 0).mean())
    yrs = (1 + combined).groupby(combined.index.year).prod() - 1
    print(f"\n== COMBINED ({', '.join(results)}), capital split 1/{n} each")
    print(f"{len(t_all)} trades ({len(t_all) / len(yrs):.0f} a year), {t_all.profit.mean():+.3f}% of the market's share per trade, "
          f"years+ {(yrs > 0).sum()}/{len(yrs)}")
    print("account:", {k: round(float(v), 2) for k, v in m.items()})
    print("years %:", (100 * yrs).round(1).to_dict())
    print("correlation of daily returns:", daily_all.corr().round(2).values.tolist())

# ---------- save + HTML dashboard (same dashboard as scripts/run_backtest.py) ----------
names = list(results)
tag = ("_".join(names) if n > 1 else f"{names[0]}_{markets[0][1]}") + f"_{args.start}_{args.end}_{args.sizing}" + \
      ("_cash" if args.cash else "") + (f"_lev{args.leverage}" if args.leverage != 1 else "")
run_dir = f"{ROOT}/results/month_end_stocks_bonds/{tag}"
os.makedirs(run_dir, exist_ok=True)
STARTING_CAPITAL = 10000
dash = pd.concat([r[0].assign(asset=k, side=1, entry=r[3].stock[r[0].entry_date].values,
                              exit=r[3].stock[r[0].exit_date].values, reason=r[0].side, gross_pips=r[0].gross_pct)
                  for k, r in results.items()])
dash.to_csv(f"{run_dir}/trades.csv", index=False)
# one P&L column per market, each started with 1/n of the capital; the dashboard adds them up
pd.concat({k: STARTING_CAPITAL / n * ((1 + r[1]).cumprod() - 1) for k, r in results.items()}, axis=1).ffill().fillna(0) \
    .to_csv(f"{run_dir}/equity.csv")
if not args.no_dashboard:
    from trading.backtesting.trade_dashboard import build_dashboard
    prices = [r[3].loc[r[5], ["stock"]].rename(columns={"stock": "Close"}) for r in results.values()]
    # benchmark: buying the S&P 500 and holding it (price only, dividends not included)
    sp500 = load_long_stock() if args.source == "long" else load_oanda_close("SPX500_USD")
    build_dashboard(run_dir, prices, {"pairs": names, "strategy_name": "month_end_stocks_bonds",
                                      "starting_capital": STARTING_CAPITAL, "profit_unit": "%",
                                      "benchmark": {"name": "S&P 500 buy and hold", "price": sp500}})
print("saved to", run_dir)
