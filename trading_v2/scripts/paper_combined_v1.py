# Paper trades BOTH strategies together in ONE OANDA practice account, the way they will run for real:
#   1. month-end stocks vs bonds (4 markets) with a stop 2 x ATR(10) below the entry          (H178)
#   2. RSI(2) snap-back on 12 index CFDs, any day of the month, with a 3 x ATR(10) stop       (H156 + H167)
# Sizes are the FTMO pick from H178: month-end 0.6 (each of 4 markets gets 0.6/4 of the account),
# RSI(2) 1.0 (each of 12 markets gets 1/12). Change them in configs/live/combined_paper.yaml.
#
# Why one bot: both strategies trade SPX500, DE30, UK100 and CH20, and OANDA keeps ONE net position per market.
# So each strategy keeps its own "book" for each market here (side, units, entry, stop), and the bot only trades
# the difference between the sum of the books and the real OANDA position. Nothing is skipped because the other
# strategy is in the market. Each book's stop is its own stop order on OANDA for exactly that book's units, so a
# stop that fills takes out that book and leaves the other strategy's units alone.
#
# Rules (do not change them, they are the ones tested in notebooks/hypotheses/h178_month_end_stop_plus_rsi2.ipynb):
#   month-end: signal 4 trading days before the last trading day; gap = stock month-to-date return - bond's.
#              gap <= -2%: buy at the signal close, sell at the month-end close.
#              gap >= +2%: buy at the month-end close, sell at the close of the 3rd trading day of next month.
#   RSI(2):    RSI(2) < 10 and close above its 200-day average: buy at the close; RSI(2) > 90 and close below it:
#              sell short. Exit at the close when RSI(2) is back at 50, or after 10 trading days.
#              After an exit (or a stop) there is no new trade in that market on the same day.
#   stops:     entry -/+ k x ATR(10) of the index (true range of daily bars), working from the next day.
#
# Run it ONCE every weekday between 16:45 and 16:58 New York time (the live price then stands in for the 17:00
# daily close; H180 showed deciding earlier loses part of the edge).
#   env PYTHONPATH=src python scripts/paper_combined.py            (places orders on practice)
#   env PYTHONPATH=src python scripts/paper_combined.py --dry-run  (only prints what it would do, saves nothing)
#   env PYTHONPATH=src python scripts/paper_combined.py --now      (real run now, outside the time window)
#   cron: 50 * * * *  (runs hourly; it exits straight away unless it is 16:45-16:58 New York time)
# It replaces scripts/paper_month_end.py and scripts/paper_rsi2.py: don't run those any more.
import os
import sys
import json
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo

from trading.utils.config import load_config
from trading.research.intraday_tools import rsi

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paper_month_end import daily_action, last_close_of_previous_month, to_account_currency   # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NEW_YORK = ZoneInfo("America/New_York")


# ---------- prices ----------

def trading_date(utc_times):
    # OANDA dates a daily bar by its 17:00 New York open, so New York time + 7h gives the trading date
    return (pd.to_datetime(utc_times).dt.tz_localize("UTC").dt.tz_convert(NEW_YORK)
            + pd.Timedelta(hours=7)).dt.tz_localize(None).dt.normalize()


def daily_bars(broker, pair, today):
    # completed daily bars before today, then today's bar so far (its close is the live price)
    candles = broker.candles(pair, count=400, granularity="D")
    bars = candles[["MidOpen", "MidHigh", "MidLow", "MidClose"]].set_index(trading_date(candles["Time"]))
    bars = bars[bars.index < today]
    bars = bars[~bars.index.duplicated(keep="last")]
    bars.loc[today] = broker.today_bar(pair)
    return bars


def atr(bars, days):
    c = bars.MidClose
    tr = pd.concat([bars.MidHigh - bars.MidLow, (bars.MidHigh - c.shift()).abs(), (bars.MidLow - c.shift()).abs()],
                   axis=1).max(axis=1)
    return float(tr.rolling(days).mean().iloc[-1])


# ---------- the two strategies (each returns "buy", "sell", "close" or "none") ----------

def rsi2_action(closes, today, book, p):
    r = float(rsi(closes, 2).iloc[-1])
    avg = closes.rolling(p["trend_days"]).mean().iloc[-1]
    info = {"rsi2": round(r, 1), "avg200": None if pd.isna(avg) else round(float(avg), 2)}
    if book.get("side"):
        held = int((closes.index > pd.Timestamp(book["entry_date"])).sum())      # trading days since the entry
        if book["side"] * (r - p["exit_rsi"]) >= 0:
            return "close", {**info, "reason": "rsi 50"}
        if held >= p["max_hold"]:
            return "close", {**info, "reason": f"{p['max_hold']} days"}
        return "none", info
    if pd.isna(avg) or book.get("last_exit") == str(today.date()):
        return "none", info                    # no new trade on the day a trade in this market ended
    if r < p["entry_rsi"] and closes.iloc[-1] > avg:
        return "buy", info
    if r > 100 - p["entry_rsi"] and closes.iloc[-1] < avg:
        return "sell", info
    return "none", info


def month_end_action(broker, m, today, book, p):
    stock, bond = m["stock"], m["bond"]
    prev = {"stock": last_close_of_previous_month(broker, stock, today),
            "bond": last_close_of_previous_month(broker, bond, today)}
    live = {"stock": sum(broker.price(stock)) / 2, "bond": sum(broker.price(bond)) / 2}
    state = {"open": bool(book.get("side")), "exit_date": book.get("exit_date"), "gap": book.get("gap")}
    action, state = daily_action(today, prev, live, state, p, m["calendar"])
    gap = (live["stock"] / prev["stock"] - 1) - (live["bond"] / prev["bond"] - 1)
    info = {"gap_mtd_pct": round(100 * gap, 2), "exit_date": state.get("exit_date")}
    book["gap"] = state.get("gap")
    if action == "buy":
        book["exit_date"] = state["exit_date"]
    return {"buy": "buy", "sell": "close"}.get(action, "none"), info


# ---------- one run ----------

def run(broker, now, cfg, books, dry_run=False):
    today = pd.Timestamp(now.date())
    summary = broker.account_summary()
    nav, currency = summary["nav"], summary["currency"]
    me, r2 = cfg["month_end"], cfg["rsi2"]
    books.setdefault("month_end", {})
    books.setdefault("rsi2", {})
    lines, time_ny = [], now.strftime("%Y-%m-%d %H:%M")
    empty = {"side": 0, "units": 0, "entry_date": None, "entry_price": None, "stop_price": None, "stop_id": None}

    # 1. stops that filled since the last run: that book is now flat
    for strategy in ("month_end", "rsi2"):
        for pair, book in books[strategy].items():
            if book.get("side") and book.get("stop_id"):
                s = broker.order_state(book["stop_id"])
                if s["state"] == "FILLED":
                    day = trading_date(pd.Series([pd.Timestamp(s["fill_time"]).tz_convert(None)])).iloc[0]
                    lines.append({"time_ny": time_ny, "strategy": strategy, "market": pair, "action": "stopped",
                                  "units": -book["units"], "price": s["fill_price"], "stop_price": book["stop_price"],
                                  "entry_date": book["entry_date"], "entry_price": book["entry_price"]})
                    keep = {k: book.get(k) for k in ("gap",) if k in book}
                    books[strategy][pair] = {**empty, **keep, "last_exit": str(day.date())}
                elif s["state"] != "PENDING":
                    lines.append({"time_ny": time_ny, "strategy": strategy, "market": pair, "action": "warning",
                                  "note": f"stop order {book['stop_id']} is {s['state']}, book kept without a stop"})
                    book["stop_id"] = None

    # 2. what each strategy wants in each market today
    bars, decisions = {}, []        # decisions: (strategy, pair, action, info, leverage, n markets, stop k)
    for m in me["markets"]:
        book = books["month_end"].setdefault(m["stock"], dict(empty))
        action, info = month_end_action(broker, m, today, book, me)
        decisions.append(("month_end", m["stock"], action, info, me["leverage"], len(me["markets"]), me["stop_atr"]))
    for pair in r2["symbols"]:
        bars[pair] = daily_bars(broker, pair, today)
        book = books["rsi2"].setdefault(pair, dict(empty))
        action, info = rsi2_action(bars[pair].MidClose, today, book, r2)
        decisions.append(("rsi2", pair, action, info, r2["leverage"], len(r2["symbols"]), r2["stop_atr"]))

    # 3. new books
    new_books = {s: {k: dict(v) for k, v in books[s].items()} for s in ("month_end", "rsi2")}
    opening, closing = [], []
    for strategy, pair, action, info, lev, n, k in decisions:
        book = new_books[strategy][pair]
        line = {"time_ny": time_ny, "strategy": strategy, "market": pair, "action": action, **info}
        if action == "close":
            closing.append((strategy, pair, dict(book)))
            line.update(units=-book["units"], entry_date=book["entry_date"], entry_price=book["entry_price"])
            new_books[strategy][pair] = {**empty, "gap": book.get("gap"), "last_exit": str(today.date())}
        elif action in ("buy", "sell"):
            if pair not in bars:
                bars[pair] = daily_bars(broker, pair, today)
            live = float(bars[pair].MidClose.iloc[-1])
            side = 1 if action == "buy" else -1
            price_acct = to_account_currency(broker, live, pair.split("_")[-1], currency)
            decimals = broker.units_precision(pair)
            units = round(nav * lev / n / price_acct, decimals) if decimals > 0 else int(nav * lev / n / price_acct)
            if units <= 0:
                line["note"] = "skipped: size is below OANDA's minimum"
            else:
                a = atr(bars[pair], cfg["atr_days"])
                stop = round(live - side * k * a, broker.price_precision(pair))
                new_books[strategy][pair] = {**book, "side": side, "units": side * units, "entry_date": str(today.date()),
                                             "entry_price": live, "stop_price": stop, "stop_id": None}
                opening.append((strategy, pair))
                line.update(units=side * units, price=live, atr=round(a, 2), stop_price=stop)
        lines.append(line)

    # 4. trade each market once: cancel the stops of closing books, then send the difference to the target
    for pair in sorted({p for _, p, *_ in decisions}):
        changed = [c for c in closing if c[1] == pair] + [o for o in opening if o[1] == pair]
        if not changed:
            target = sum(new_books[s][pair]["units"] for s in ("month_end", "rsi2") if pair in new_books[s])
            position = broker.position(pair)
            if abs(position - target) > 1e-9:
                # something else changed this market (a manual trade, an old bot): report it, don't trade it
                lines.append({"time_ny": time_ny, "strategy": "account", "market": pair, "action": "warning",
                              "position_before": position, "target": target,
                              "note": "OANDA position is not the sum of the books"})
            continue
        for strategy, _, old in [c for c in closing if c[1] == pair]:
            if old.get("stop_id") and not dry_run:
                if not broker.cancel_order(old["stop_id"]) and broker.order_state(old["stop_id"])["state"] == "FILLED":
                    lines.append({"time_ny": time_ny, "strategy": strategy, "market": pair, "action": "note",
                                  "note": "stop filled just before the exit, so that book was already flat"})
        target = sum(new_books[s][pair]["units"] for s in ("month_end", "rsi2") if pair in new_books[s])
        position = broker.position(pair)
        decimals = broker.units_precision(pair)
        order = round(target - position, decimals) if decimals > 0 else int(round(target - position))
        line = {"time_ny": time_ny, "strategy": "account", "market": pair, "action": "order",
                "position_before": position, "target": target, "units": order}
        if order and not dry_run:
            response = broker.market_order(pair, order, stop_loss=None)
            fill = response.get("orderFillTransaction")
            if fill is None:
                # not filled (market closed?): keep yesterday's books for this market so the next run tries again
                line["note"] = "ORDER NOT FILLED: " + str(response.get("orderCancelTransaction", {}).get("reason"))
                for s in ("month_end", "rsi2"):
                    if pair in books[s]:
                        new_books[s][pair] = books[s][pair]
                lines.append(line)
                continue
            line["price"] = float(fill["price"])
            for s, p in opening:
                if p == pair:
                    new_books[s][pair]["entry_price"] = float(fill["price"])
        lines.append(line)
        # the stop of each new book: an order for minus that book's units
        for s, p in opening:
            if p == pair and not dry_run:
                b = new_books[s][pair]
                b["stop_id"] = broker.exit_stop_order(pair, -b["units"], b["stop_price"], broker.price_precision(pair))
                if b["stop_id"] is None:
                    lines.append({"time_ny": time_ny, "strategy": s, "market": pair, "action": "warning",
                                  "note": "OANDA refused the stop order: this book has NO stop"})

    books["month_end"], books["rsi2"] = new_books["month_end"], new_books["rsi2"]
    return books, lines


def main():
    dry_run = "--dry-run" in sys.argv
    cfg = load_config("live/combined_paper.yaml")
    out_dir = os.path.join(ROOT, cfg["output_dir"])
    os.makedirs(out_dir, exist_ok=True)
    state_file = os.path.join(out_dir, "books.json")
    books = json.load(open(state_file)) if os.path.exists(state_file) else {}

    now = datetime.now(NEW_YORK)
    in_window = now.weekday() < 5 and now.hour == 16 and 45 <= now.minute <= 58
    if not in_window and not dry_run and "--now" not in sys.argv:
        return
    if books.get("_last_run") == str(now.date()) and not dry_run:
        return                                   # already ran today

    from trading.live.oanda_broker import OandaBroker
    broker = OandaBroker()
    broker.check_token()
    books, lines = run(broker, now, cfg, books, dry_run)
    for line in lines:
        print(line)
    if not dry_run:
        books["_last_run"] = str(now.date())
        json.dump(books, open(state_file, "w"), indent=1)
        log_file = os.path.join(out_dir, "log.csv")
        old = pd.read_csv(log_file) if os.path.exists(log_file) else pd.DataFrame()
        pd.concat([old, pd.DataFrame(lines)], ignore_index=True).to_csv(log_file, index=False)


if __name__ == "__main__":
    main()
