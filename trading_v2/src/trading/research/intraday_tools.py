# Shared helpers for the frequent-trading hypothesis notebooks (H74-H82).
# Every notebook builds a trades table with these columns:
#   symbol, entry_time, exit_time (UTC, naive), side (+1 long / -1 short), entry, exit, entry_i, exit_i
#   (entry_i / exit_i are bar positions in that symbol's bars, used by the random baseline)
# and these helpers add costs, check the pass rules, run the walk-forward and the FTMO simulator.
import os
import numpy as np
import pandas as pd
import trading.utils.constants as constants
from trading.utils.data_manipulation import preprocess_csv
from trading.research.fx_hypothesis_tools import monthly_rates
from trading.backtesting.prop_challenge import simulate, summary

TIMEZONES = {"ny": "America/New_York", "london": "Europe/London", "frankfurt": "Europe/Berlin",
             "tokyo": "Asia/Tokyo", "sydney": "Australia/Sydney"}


def load_bars(symbol, years, timeframe, cache=True):
    # OANDA bars (Mid OHLC + SpreadClose); indices are in the indices folder, everything else in forex.
    # Adds local-time columns ny, london and frankfurt (time zones with summer time handled).
    # cache=True saves the result in data/cache/ so the next load is fast (M5 files are big).
    cache_path = os.path.join(constants.RAW_DATA_DIR, "..", "cache", f"{symbol}_{timeframe}_{years[0]}_{years[-1]}.pkl")
    if cache and os.path.exists(cache_path):
        bars = pd.read_pickle(cache_path)
        print(f"{symbol} {timeframe}: {len(bars)} bars from cache, {bars.index[0].date()} to {bars.index[-1].date()}")
        return bars
    yearly = []
    for year in years:
        for folder in ["indices", "forex"]:
            path = os.path.join(constants.RAW_DATA_DIR, "oanda", folder, symbol, str(year), timeframe, "merged",
                                f"{symbol}_{year}.csv")
            if os.path.exists(path):
                data_list = preprocess_csv(path)
                if data_list is not None and len(data_list):
                    yearly.append(data_list[["MidOpen", "MidHigh", "MidLow", "MidClose", "SpreadClose"]])
                break
    if not yearly:
        raise RuntimeError(f"No {timeframe} data for {symbol}: download it with scripts/generate_backtest_data.py")
    bars = pd.concat(yearly)
    bars.index = pd.to_datetime(bars.index)
    bars = bars.sort_index()
    bars = bars[~bars.index.duplicated(keep="last")]
    missing = bars.SpreadClose <= 0                                   # OANDA has no bid/ask on older bars (spread 0)
    if missing.all():
        raise RuntimeError(f"{symbol}: no bar has a spread, so costs can't be estimated")
    if missing.any():
        fill = bars.SpreadClose[~missing].median()
        bars.loc[missing, "SpreadClose"] = fill
        print(f"{symbol}: {100 * missing.mean():.0f}% of bars had no spread, given the median of the rest ({fill:.4g})")
    utc = bars.index.tz_localize("UTC")
    for name, tz in TIMEZONES.items():
        bars[name] = utc.tz_convert(tz).tz_localize(None)
    bars.attrs["step"] = (bars.index[1:] - bars.index[:-1]).min()   # bar length (shortest gap between bars)
    print(f"{symbol} {timeframe}: {len(bars)} bars, {bars.index[0].date()} to {bars.index[-1].date()}")
    if cache:
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        bars.to_pickle(cache_path)
    return bars


_cache = {}       # daily_sessions and bar_at results, so each grid setting doesn't redo them (slow on M5)


def daily_sessions(bars, tz, open_time, close_time):
    # one row per local trading day: position and price of the bar that starts at open_time (its open)
    # and of the bar that ends at close_time (its close). Times as "HH:MM" in local time.
    key = ("sessions", id(bars), len(bars), tz, open_time, close_time)
    if key not in _cache:
        _cache[key] = _daily_sessions(bars, tz, open_time, close_time)
    return _cache[key].copy()


def _daily_sessions(bars, tz, open_time, close_time):
    local = bars[tz]
    step = bars.attrs["step"]
    o = pd.Timestamp(open_time).time()
    c = (pd.Timestamp(close_time) - step).time()          # the bar that starts one step before the close
    pos = pd.Series(np.arange(len(bars)), index=bars.index)
    day = local.dt.normalize()
    opens = pos[local.dt.time.values == o]
    closes = pos[local.dt.time.values == c]
    out = pd.DataFrame({"open_i": pd.Series(opens.values, index=day[opens.index].values),
                        "close_i": pd.Series(closes.values, index=day[closes.index].values)})
    out = out.dropna().astype(int)
    out = out[out.close_i > out.open_i]
    out["open"] = bars.MidOpen.values[out.open_i]
    out["close"] = bars.MidClose.values[out.close_i]
    out.index.name = "day"
    return out


def daily_bars(bars):
    # OANDA daily bars start at 17:00 New York; label each with the day it closes and drop the Sunday stub bars.
    # Keeps the bar positions (column i) so trades can still point at rows of the full bars table.
    d = bars.copy()
    d["i"] = np.arange(len(d))
    d["day"] = (d.index + pd.Timedelta(hours=3)).normalize()
    return d[d.day.dt.dayofweek < 5]


def trade(symbol, bars, entry_i, exit_i, side, entry=None, exit=None, at_close=False):
    # one trades-table row. Default prices: the open of the entry bar and the close of the exit bar.
    # at_close=True means "enter at the close of bar entry_i" (stored as entry_i + 1, the first bar held).
    # exit_time is the end of the exit bar.
    step = bars.attrs["step"]
    if at_close:
        entry = bars.MidClose.values[entry_i] if entry is None else entry
        entry_time = bars.index[entry_i] + step
        entry_i += 1
    else:
        entry_time = bars.index[entry_i]
    return {"symbol": symbol, "entry_time": entry_time, "exit_time": bars.index[exit_i] + step,
            "side": side, "entry": bars.MidOpen.values[entry_i] if entry is None else entry,
            "exit": bars.MidClose.values[exit_i] if exit is None else exit, "entry_i": entry_i, "exit_i": exit_i}


def bar_at(bars, tz, days, hhmm):
    # position of the bar that starts at local time hhmm on each day (NaN where there is none)
    key = ("lookup", id(bars), len(bars), tz)
    if key not in _cache:
        lookup = pd.Series(np.arange(len(bars)), index=bars[tz].values)
        _cache[key] = lookup[~lookup.index.duplicated()]
    lookup = _cache[key]
    return lookup.reindex(pd.DatetimeIndex(days) + pd.Timedelta(hhmm + ":00")).values


def limit_fill(bars, first_i, last_i, side, limit, fill_through_pct):
    # first bar from first_i to last_i where a limit order at `limit` fills, or None.
    # Bars are mid prices, so a buy fills when the ask (mid low + half spread) trades below the limit by
    # fill_through_pct (cautious: just touching the limit isn't counted, since others queue ahead of us).
    low, high, half = bars.MidLow.values, bars.MidHigh.values, bars.SpreadClose.values / 2
    need = fill_through_pct / 100 * limit
    for i in range(first_i, last_i + 1):
        if side == 1 and low[i] + half[i] <= limit - need:
            return i
        if side == -1 and high[i] - half[i] >= limit + need:
            return i
    return None


def buy_entry(bars, first_i, last_i, price, offset_pct, fill_through_pct):
    # a buy placed at bar first_i: a limit offset_pct below price (open until last_i), or a market order if
    # offset_pct is None. Returns (bar, price paid, is_limit) or None if the limit never fills.
    if offset_pct is None:
        return first_i, bars.MidOpen.values[first_i], False
    limit = price * (1 - offset_pct / 100)
    f = limit_fill(bars, first_i, last_i, 1, limit, fill_through_pct)
    return None if f is None else (f, limit, True)


def exit_at_target(bars, first_i, last_i, target, fill_through_pct):
    # long exit: a sell limit at target from first_i to last_i, else a market sell at the close of last_i.
    # Returns (bar, price, is_limit).
    if target is not None and first_i <= last_i:
        f = limit_fill(bars, first_i, last_i, -1, target, fill_through_pct)
        if f is not None:
            return f, target, True
    return last_i, bars.MidClose.values[last_i], False


def session_ranges(bars, sessions):
    # high - low of each session (sessions from daily_sessions), as % of the open
    high, low = bars.MidHigh.values, bars.MidLow.values
    r = [high[a:z + 1].max() - low[a:z + 1].min() for a, z in zip(sessions.open_i, sessions.close_i)]
    return pd.Series(100 * np.array(r) / sessions.open.values, index=sessions.index)


def wilder_parts(close, n):
    # Wilder's average up and down moves, so RSI can be updated with today's price before the close:
    # up_today = up[yesterday] * (1 - 1/n) + max(change, 0) / n, same for down, RSI = 100 - 100 / (1 + up / down)
    change = close.diff()
    up = change.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    down = (-change.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return up.values, down.values


def rsi(close, n):
    # Wilder RSI
    change = close.diff()
    up = change.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    down = (-change.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / down.replace(0, np.nan))


def finish(trades, bars_by_symbol, cfg):
    # adds gross %, cost % (half the spread each side + slippage each side), financing % for each New York
    # 17:00 rollover held (longs pay rate + markup, shorts receive rate - markup), net %, year
    t = pd.DataFrame(trades).reset_index(drop=True)
    if t.empty:
        for c in ["gross", "cost", "financing", "net", "year"]:
            t[c] = []
        return t
    t["gross"] = 100 * t.side * (t.exit / t.entry - 1)
    # limit_entry=True rows: the entry price is the limit we paid, so no spread or slippage on the way in
    # limit_exit=True rows: the exit was a take-profit limit, so no spread or slippage on the way out either
    limit = t["limit_entry"].fillna(False).astype(bool).values if "limit_entry" in t else np.zeros(len(t), bool)
    limit_x = t["limit_exit"].fillna(False).astype(bool).values if "limit_exit" in t else np.zeros(len(t), bool)
    # cfg "fixed_spread_points" {symbol: points} or "fixed_spread_%" {symbol: % of price} replaces OANDA's spread
    # (e.g. a futures tick), "commission_%" is per side, "dividend_yield_%" {symbol: %} is credited to longs per night
    # (a futures holder pays rate - dividends), and "no_financing: true" drops the overnight charge
    fixed, fixed_pct = cfg.get("fixed_spread_points") or {}, cfg.get("fixed_spread_%") or {}
    spread = []
    for s, ei, xi, e, x, lim, lim_x in zip(t.symbol, t.entry_i, t.exit_i, t.entry, t.exit, limit, limit_x):
        sp = bars_by_symbol[s].SpreadClose.values
        sp_in, sp_out = (fixed[s], fixed[s]) if s in fixed else (sp[max(ei - 1, 0)], sp[xi])
        if s in fixed_pct:
            sp_in, sp_out = fixed_pct[s] / 100 * e, fixed_pct[s] / 100 * x
        spread.append(100 * ((0 if lim else 0.5 * sp_in / e) + (0 if lim_x else 0.5 * sp_out / x)))
    sides = 2 - limit.astype(int) - limit_x.astype(int)
    t["cost"] = np.array(spread) + sides * cfg["slippage_%"] + 2 * cfg.get("commission_%", 0)
    ny_a = pd.DatetimeIndex(t.entry_time).tz_localize("UTC").tz_convert(TIMEZONES["ny"]).tz_localize(None)
    ny_b = pd.DatetimeIndex(t.exit_time).tz_localize("UTC").tz_convert(TIMEZONES["ny"]).tz_localize(None)
    first = (ny_a - pd.Timedelta(hours=17)).normalize() + pd.Timedelta(days=1)
    last = (ny_b - pd.Timedelta(hours=17)).normalize()
    nights = np.maximum((last - first).days.values + 1, 0)           # New York 17:00 rollovers held
    rates = monthly_rates({s[-3:] for s in t.symbol})
    rate = np.zeros(len(t))
    for ccy in rates.columns:
        r = rates[ccy].dropna()
        rows = np.flatnonzero(t.symbol.str[-3:].values == ccy)
        if len(r) and len(rows):
            k = np.searchsorted(r.index.values, pd.DatetimeIndex(t.entry_time[rows]).values, side="right") - 1
            rate[rows] = np.where(k >= 0, r.values[np.maximum(k, 0)], 0.0)
    div = t.symbol.map(cfg.get("dividend_yield_%") or {}).fillna(0).values
    fin = -(t.side.values * (rate - div) + cfg["financing_markup_%"]) * nights / 365
    if cfg.get("no_financing"):
        fin = np.zeros(len(t))
    t["financing"] = fin
    t["net"] = t.gross - t.cost + t.financing
    t["year"] = pd.to_datetime(t.entry_time).dt.year
    return t


def trade_stats(t, col="net"):
    x = t[col]
    if len(x) < 2:
        return pd.Series({"trades": len(x)})
    by_year = t.groupby("year")[col].sum()
    rest = t.loc[t.year != by_year.idxmax(), col]
    return pd.Series({"trades": len(x), "per year": round(len(x) / t.year.nunique(), 1),
                      "mean %": round(x.mean(), 4), "t": round(x.mean() / x.std() * np.sqrt(len(x)), 2),
                      "win %": round(100 * (x > 0).mean(), 1), "years + %": round(100 * (by_year > 0).mean(), 1),
                      "mean w/o best year %": round(rest.mean(), 4) if len(rest) else np.nan,
                      "gross %": round(t.gross.mean(), 4), "cost %": round(t.cost.mean() - t.financing.mean(), 4)})


def random_baseline(t, bars_by_symbol, runs=500, seed=0):
    # same symbol, side and number of bars held, but a random entry bar in the same year (gross %).
    # Returns the % of random runs whose average gross the strategy beats.
    rng = np.random.default_rng(seed)
    hold = (t.exit_i - t.entry_i + 1).clip(lower=1).values         # bars from the close before entry to exit
    side = t.side.values
    groups = t.groupby(["symbol", "year"]).indices
    year_pos = {(s, y): np.flatnonzero(bars_by_symbol[s].index.year == y) for s, y in groups}
    means = []
    for _ in range(runs):
        g = np.empty(len(t))
        for (s, y), idx in groups.items():
            close = bars_by_symbol[s].MidClose.values
            pos = year_pos[(s, y)]
            i = pos[rng.integers(len(pos), size=len(idx))]
            j = np.minimum(i + hold[idx], len(close) - 1)
            g[idx] = 100 * side[idx] * (close[j] / close[i] - 1)
        means.append(g.mean())
    return 100 * (t.gross.mean() > np.array(means)).mean()


def pass_rules(t, beats, n_tests, label, drop_years=None):
    # drop_years (e.g. [2008, 2009]) adds the rule "still positive without those years"
    s = trade_stats(t)
    print(f"{label}: {int(s['trades'])} trades ({s['per year']} a year), net {s['mean %']:.4f}% per trade "
          f"(gross {s['gross %']:.4f}%, costs {s['cost %']:.4f}%), t {s['t']:.2f}, years + {s['years + %']:.0f}%, "
          f"beats {beats:.0f}% of random entries")
    checks = {"t > 2": s["t"] > 2, "60%+ years positive": s["years + %"] >= 60,
              "positive without best year": s["mean w/o best year %"] > 0,
              "beats 95% of random entries": beats >= 95, "at least 30 trades": s["trades"] >= 30}
    if drop_years:
        rest = t.loc[~t.year.isin(drop_years), "net"]
        checks[f"positive without {', '.join(map(str, drop_years))}"] = len(rest) > 0 and rest.mean() > 0
    for k, v in checks.items():
        print(f"   {'yes' if v else 'NO '}  {k}")
    print(f"   (luck-proof bar for {n_tests} ideas: t > 3.0: {'met' if s['t'] > 3 else 'not met'})")
    print("   =>", "PASS" if all(checks.values()) else "FAIL")
    return all(checks.values())


def walk_forward(trades_by_setting, years, train_years, min_trades=20):
    # trades_by_setting: {setting name: finished trades over ALL research years}.
    # For each test year: pick the setting with the best net t-stat over the previous train_years, then keep only
    # that setting's trades in the test year. Nothing from a test year is used to choose its own setting.
    chosen, oos = [], []
    for y in years[train_years:]:
        train = range(y - train_years, y)
        best, best_t = None, -np.inf
        for name, t in trades_by_setting.items():
            tr = t[t.year.isin(train)]
            if len(tr) >= min_trades and tr.net.std() > 0:
                tt = tr.net.mean() / tr.net.std() * np.sqrt(len(tr))
                if tt > best_t:
                    best, best_t = name, tt
        if best is None:
            continue
        test = trades_by_setting[best]
        test = test[test.year == y]
        chosen.append({"test year": y, "chosen": best, "train t": round(best_t, 2), "test trades": len(test),
                       "test net %": round(test.net.sum(), 2)})
        oos.append(test.assign(setting=best))
    return pd.DataFrame(chosen), (pd.concat(oos, ignore_index=True) if oos else pd.DataFrame())


def ftmo_check(t, cfg, prop_cfg):
    # turns trades into daily account returns (each trade uses leverage / number of markets of the account,
    # P&L booked on the exit day) and runs the FTMO 2-Step simulator at each leverage in the config
    if t.empty:
        print("no trades")
        return None
    n_markets = t.symbol.nunique()
    day = pd.to_datetime(t.exit_time).dt.normalize()
    daily = (t.net / 100).groupby(day).sum() / n_markets
    days = pd.bdate_range(daily.index.min(), daily.index.max())
    daily = daily.reindex(days).fillna(0)
    rows = [summary(simulate(daily, prop_cfg["rules"], lev), prop_cfg["rules"], lev) for lev in cfg["ftmo_leverages"]]
    return pd.DataFrame(rows)
