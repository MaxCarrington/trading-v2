# Paper trades the RSI(2) index rule (H146 v1.0, frozen) on the OANDA practice account, 12 index CFDs at once.
# Rules (do not change them, they are the ones tested in notebooks/hypotheses/h146_rsi2_indices_daily*.ipynb):
#   RSI(2) of daily closes < 10 and close above its 200-day average: buy at the close
#   RSI(2) > 90 and close below the 200-day average: sell short at the close
#   exit at the close when RSI(2) gets back to 50 (above for a long, below for a short) or after 10 trading days
#   only trades in the month-end idle window (trading day 4 of the month up to 5 trading days before the last),
#   so it never holds anything while the month-end bot (scripts/paper_month_end.py) can be in the same markets.
#   Live difference: the backtest dropped trades that would have ended after the window; live we can't know that in
#   advance, so an open trade is closed on the last idle day instead.
# Each market gets balance / 12 x leverage (configs/live/rsi2_paper.yaml).
#
# Run it ONCE every weekday between 16:30 and 16:55 New York time, like the month-end bot (the live price then
# stands in for the 17:00 daily close the backtest used).
#   env PYTHONPATH=src python scripts/paper_rsi2.py            (places orders on practice)
#   env PYTHONPATH=src python scripts/paper_rsi2.py --dry-run  (only prints what it would do, saves nothing)
#   cron: 40 * * * *  (runs hourly; it exits straight away unless it is 16:30-16:55 New York time)
import os
import sys
import json
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo

from trading.utils.config import load_config
from trading.research.intraday_tools import rsi
from trading.research.fx_hypothesis_tools import in_idle_window

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NEW_YORK = ZoneInfo("America/New_York")


def is_last_idle_day(day):
    # idle today, but the next weekday is not
    return bool(in_idle_window([day])[0]) and not bool(in_idle_window([day + pd.offsets.BDay(1)])[0])


def decide(closes, today, state, p):
    # closes: daily closes up to and including today's (live) close, oldest first
    # state: {"side": 0/1/-1, "entry_date": "YYYY-MM-DD" or None, "held": days held so far}
    # returns (action, new_state, info) with action "buy", "sell", "close" or "none"
    state = dict(state)
    r = float(rsi(closes, 2).iloc[-1])
    avg = closes.rolling(p["trend_days"]).mean().iloc[-1]
    up = bool(closes.iloc[-1] > avg)
    info = {"rsi2": round(r, 1), "close": float(closes.iloc[-1]), "avg200": None if pd.isna(avg) else round(float(avg), 2)}
    idle = bool(in_idle_window([today])[0])

    if state.get("side"):
        state["held"] = state.get("held", 0) + 1
        back_to_50 = state["side"] * (r - p["exit_rsi"]) >= 0
        if back_to_50 or state["held"] >= p["max_hold"] or not idle or is_last_idle_day(today):
            info["exit_reason"] = ("rsi 50" if back_to_50 else f"{p['max_hold']} days" if state["held"] >= p["max_hold"]
                                   else "end of idle window")
            return "close", {"side": 0, "entry_date": None, "held": 0}, info
        return "none", state, info

    # flat: a new trade only inside the idle window, and not on its last day (it would have to close outside it)
    if not idle or is_last_idle_day(today) or pd.isna(avg):
        return "none", state, info
    if r < p["entry_rsi"] and up:
        return "buy", {"side": 1, "entry_date": str(today.date()), "held": 0}, info
    if r > 100 - p["entry_rsi"] and not up:
        return "sell", {"side": -1, "entry_date": str(today.date()), "held": 0}, info
    return "none", state, info


def daily_closes(broker, pair, today, live_price):
    # completed daily bars (OANDA dates a daily bar by its 17:00 New York open, so +7h gives the trading date),
    # then today's live price as today's close
    candles = broker.candles(pair, count=400, granularity="D")
    dates = (pd.to_datetime(candles["Time"]).dt.tz_localize("UTC").dt.tz_convert(NEW_YORK)
             + pd.Timedelta(hours=7)).dt.tz_localize(None).dt.normalize()
    closes = pd.Series(candles["MidClose"].values, index=dates)
    closes = closes[closes.index < today]
    closes = closes[~closes.index.duplicated(keep="last")]
    closes.loc[today] = live_price
    return closes


def to_account_currency(broker, amount, currency, account_currency):
    if currency == account_currency:
        return amount
    for pair, invert in [(f"{currency}_{account_currency}", False), (f"{account_currency}_{currency}", True)]:
        try:
            mid = sum(broker.price(pair)) / 2
            return amount / mid if invert else amount * mid
        except Exception:
            continue
    raise RuntimeError(f"no OANDA price to convert {currency} into {account_currency}")


def main():
    dry_run = "--dry-run" in sys.argv
    p = load_config("live/rsi2_paper.yaml")
    out_dir = os.path.join(ROOT, p["output_dir"])
    os.makedirs(out_dir, exist_ok=True)
    state_file = os.path.join(out_dir, "state.json")
    states = json.load(open(state_file)) if os.path.exists(state_file) else {}

    now = datetime.now(NEW_YORK)
    in_window = now.weekday() < 5 and now.hour == 16 and 30 <= now.minute <= 55
    if not in_window and not dry_run and "--now" not in sys.argv:
        return
    today = pd.Timestamp(now.date())
    if states.get("_last_run") == str(today.date()) and not dry_run:
        return                                   # already ran today (held-day counts must only go up once a day)

    from trading.live.oanda_broker import OandaBroker
    broker = OandaBroker()
    summary = broker.account_summary()

    lines = []
    for pair in p["symbols"]:
        state = states.get(pair, {"side": 0, "entry_date": None, "held": 0})
        live = sum(broker.price(pair)) / 2
        closes = daily_closes(broker, pair, today, live)
        action, new_state, info = decide(closes, today, state, p)

        # safety: the real OANDA position decides, not just the saved state
        position = broker.position(pair)
        note, units = "", None
        if action in ("buy", "sell") or dry_run:
            share = summary["balance"] / len(p["symbols"]) * p["leverage"]           # account currency
            price = to_account_currency(broker, live, pair.split("_")[-1], summary["currency"])
            decimals = broker.units_precision(pair)
            units = round(share / price, decimals) if decimals > 0 else int(share / price)
        if action in ("buy", "sell") and position == 0:
            signed = units if action == "buy" else -units
            note = f"{action} {units} units"
            if units <= 0:
                note = f"skipped: {units} units is below OANDA's minimum"
                new_state = state
            elif not dry_run:
                broker.market_order(pair, signed, stop_loss=None)
        elif action in ("buy", "sell"):
            note = f"skipped: {action} but OANDA position is {position} (month-end bot?)"
            new_state = state
        elif action == "close" and position != 0 and (position > 0) == (state["side"] > 0):
            note = f"close {position} units ({info.get('exit_reason')})"
            if not dry_run:
                broker.close_position(pair)
        elif action == "close":
            note = f"skipped: close but OANDA position is {position}"

        line = {"time_ny": now.strftime("%Y-%m-%d %H:%M"), "market": pair, "action": action, "note": note, **info,
                "position_before": position, "side_after": new_state.get("side"), "held": new_state.get("held"),
                "dry_run": dry_run}
        if dry_run:
            line["size_if_traded"] = units
        print(line)
        lines.append(line)
        states[pair] = new_state

    if not dry_run:
        states["_last_run"] = str(today.date())
        json.dump(states, open(state_file, "w"))
        log_file = os.path.join(out_dir, "log.csv")
        pd.DataFrame(lines).to_csv(log_file, mode="a", header=not os.path.exists(log_file), index=False)


if __name__ == "__main__":
    main()
