# Paper trades the month-end stocks vs bonds rule on the OANDA practice account.
# Rules are the ones tested in scripts/month_end_stocks_bonds.py (do not change them):
#   signal day = 4 trading days before the last trading day of the month
#   gap = SPX month-to-date return - bond month-to-date return (from last close of previous month)
#   gap <= -2%: buy SPX on the signal day, sell on the last trading day of the month
#   gap >= +2%: buy SPX on the last trading day, sell on the 3rd trading day of next month
#
# Run it ONCE every weekday between 16:30 and 16:55 New York time (the OANDA daily bar closes at 17:00).
# The live price at that time stands in for the day's close. Most days it just logs "nothing to do".
#   env PYTHONPATH=src python scripts/paper_month_end.py            (places orders on practice)
#   env PYTHONPATH=src python scripts/paper_month_end.py --dry-run  (only prints what it would do)
import os
import sys
import json
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo
from pandas.tseries.holiday import (AbstractHolidayCalendar, Holiday, GoodFriday, USMartinLutherKingJr,
                                    USPresidentsDay, USMemorialDay, USLaborDay, USThanksgivingDay, nearest_workday)

from trading.utils.config import load_config

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NEW_YORK = ZoneInfo("America/New_York")


class NYSECalendar(AbstractHolidayCalendar):
    rules = [
        Holiday("NewYearsDay", month=1, day=1, observance=nearest_workday),
        USMartinLutherKingJr, USPresidentsDay, GoodFriday, USMemorialDay,
        Holiday("Juneteenth", month=6, day=19, start_date="2022-01-01", observance=nearest_workday),
        Holiday("IndependenceDay", month=7, day=4, observance=nearest_workday),
        USLaborDay, USThanksgivingDay,
        Holiday("Christmas", month=12, day=25, observance=nearest_workday),
    ]


def trading_days(year, month):
    # NYSE trading days of one month
    start = pd.Timestamp(year, month, 1)
    end = start + pd.offsets.MonthEnd(0)
    holidays = NYSECalendar().holidays(start, end)
    return [d for d in pd.bdate_range(start, end) if d not in holidays]


def next_month(day):
    nxt = day + pd.offsets.MonthBegin(1)
    return nxt.year, nxt.month


def daily_action(today, closes_prev_month_end, closes_now, state, params):
    # today: date (Timestamp). closes_prev_month_end / closes_now: {"stock": x, "bond": y}.
    # state: {"open": bool, "exit_date": "YYYY-MM-DD" or None, "gap": float or None}
    # returns (action, new_state) with action "buy", "sell" or "none"
    days = trading_days(today.year, today.month)
    if today not in days:
        return "none", state
    state = dict(state)

    if state.get("open") and state.get("exit_date") == str(today.date()):
        state.update(open=False, exit_date=None)
        action = "sell"
    else:
        action = "none"

    if today == days[-1 - params["days_before"]]:
        gap = ((closes_now["stock"] / closes_prev_month_end["stock"] - 1)
               - (closes_now["bond"] / closes_prev_month_end["bond"] - 1))
        state["gap"] = gap
        if gap <= -params["threshold"] and not state.get("open"):
            state.update(open=True, exit_date=str(days[-1].date()))
            return "buy", state

    if today == days[-1] and state.get("gap") is not None:
        gap, state["gap"] = state["gap"], None
        if gap >= params["threshold"] and not state.get("open"):
            exit_day = trading_days(*next_month(today))[params["days_after"] - 1]
            state.update(open=True, exit_date=str(exit_day.date()))
            # selling the "before" trade and buying the "after" trade on one day cannot both happen
            # (they need opposite gaps), so returning "buy" here is safe
            return "buy", state

    return action, state


def last_close_of_previous_month(broker, pair, today):
    # completed daily bars; OANDA dates a daily bar by its 17:00 New York open, so +7h gives the trading date
    candles = broker.candles(pair, count=60, granularity="D")
    candles["date"] = (pd.to_datetime(candles["Time"]).dt.tz_localize("UTC").dt.tz_convert(NEW_YORK)
                       + pd.Timedelta(hours=7)).dt.tz_localize(None).dt.normalize()
    before = candles[candles["date"] < today.replace(day=1)]
    return float(before["MidClose"].iloc[-1])


def main():
    dry_run = "--dry-run" in sys.argv
    params = load_config("live/month_end_paper.yaml")
    out_dir = os.path.join(ROOT, params["output_dir"])
    os.makedirs(out_dir, exist_ok=True)
    state_file = os.path.join(out_dir, "state.json")
    state = json.load(open(state_file)) if os.path.exists(state_file) else {"open": False, "exit_date": None, "gap": None}

    from trading.live.oanda_broker import OandaBroker
    broker = OandaBroker()
    now = datetime.now(NEW_YORK)
    today = pd.Timestamp(now.date())

    names = {"stock": params["stock"], "bond": params["bond"]}
    prev = {k: last_close_of_previous_month(broker, p, today) for k, p in names.items()}
    live = {k: sum(broker.price(p)) / 2 for k, p in names.items()}
    action, new_state = daily_action(today, prev, live, state, params)

    # safety: the real OANDA position decides, not just the saved state
    position = broker.position(params["stock"])
    note = ""
    if action == "buy" and position == 0:
        summary = broker.account_summary()
        balance = summary["balance"]
        if summary["currency"] == "GBP":
            balance *= sum(broker.price("GBP_USD")) / 2
        units = int(balance * params["invest_fraction"] / live["stock"])
        note = f"buy {units} units"
        if not dry_run:
            broker.market_order(params["stock"], units, stop_loss=None)
    elif action == "sell" and position != 0:
        note = f"close {position} units"
        if not dry_run:
            broker.close_position(params["stock"])
    elif action != "none":
        note = f"skipped: {action} but OANDA position is {position}"

    stock_mtd = live["stock"] / prev["stock"] - 1
    bond_mtd = live["bond"] / prev["bond"] - 1
    line = {"time_ny": now.strftime("%Y-%m-%d %H:%M"), "action": action, "note": note,
            "stock": live["stock"], "bond": live["bond"], "gap_mtd_pct": round(100 * (stock_mtd - bond_mtd), 2),
            "position_before": position, "exit_date": new_state.get("exit_date"), "dry_run": dry_run}
    print(line)
    if not dry_run:
        json.dump(new_state, open(state_file, "w"))
        log_file = os.path.join(out_dir, "log.csv")
        pd.DataFrame([line]).to_csv(log_file, mode="a", header=not os.path.exists(log_file), index=False)


if __name__ == "__main__":
    main()
