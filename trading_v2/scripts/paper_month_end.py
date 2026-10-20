# Paper trades the month-end stocks vs bonds rule on the OANDA practice account, in 3 markets at once
# (S&P 500 vs US 30y, DE30 vs Bund, UK100 vs Gilt, CH20 vs Bund; markets listed in configs/live/month_end_paper.yaml).
# Rules are the ones tested in scripts/month_end_stocks_bonds.py (do not change them):
#   signal day = 4 trading days before the last trading day of the month (each market's own exchange holidays)
#   gap = stock month-to-date return - bond month-to-date return (from last close of previous month)
#   gap <= -2%: buy the index on the signal day, sell on the last trading day of the month
#   gap >= +2%: buy the index on the last trading day, sell on the 3rd trading day of next month
# Each market gets an equal share of the balance, like the backtest (--all / --markets).
#
# Run it ONCE every weekday between 16:30 and 16:55 New York time (the OANDA daily bar closes at 17:00, which is
# what the backtest used for every market). The live price at that time stands in for the day's close.
#   env PYTHONPATH=src python scripts/paper_month_end.py            (places orders on practice)
#   env PYTHONPATH=src python scripts/paper_month_end.py --dry-run  (only prints what it would do)
#   cron: 35 * * * *  (runs hourly; it exits straight away unless it is 16:30-16:55 New York time)
import os
import sys
import json
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo
from pandas.tseries.holiday import (AbstractHolidayCalendar, Holiday, GoodFriday, EasterMonday, USMartinLutherKingJr,
                                    USPresidentsDay, USMemorialDay, USLaborDay, USThanksgivingDay, nearest_workday,
                                    next_monday, next_monday_or_tuesday, MO, DateOffset)

from pandas.tseries.offsets import Easter, Day

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


class LSECalendar(AbstractHolidayCalendar):
    # London Stock Exchange: England bank holidays (one-off royal holidays not included)
    rules = [
        Holiday("NewYearsDay", month=1, day=1, observance=next_monday),
        GoodFriday, EasterMonday,
        Holiday("EarlyMay", month=5, day=1, offset=DateOffset(weekday=MO(1))),
        Holiday("SpringBank", month=5, day=31, offset=DateOffset(weekday=MO(-1))),
        Holiday("SummerBank", month=8, day=31, offset=DateOffset(weekday=MO(-1))),
        Holiday("Christmas", month=12, day=25, observance=next_monday),
        Holiday("BoxingDay", month=12, day=26, observance=next_monday_or_tuesday),
    ]


class XETRACalendar(AbstractHolidayCalendar):
    # Frankfurt Xetra: closed on these days, no moving to Monday when they fall at a weekend
    rules = [
        Holiday("NewYearsDay", month=1, day=1), GoodFriday, EasterMonday,
        Holiday("LabourDay", month=5, day=1),
        Holiday("ChristmasEve", month=12, day=24), Holiday("Christmas", month=12, day=25),
        Holiday("BoxingDay", month=12, day=26), Holiday("NewYearsEve", month=12, day=31),
    ]


class SIXCalendar(AbstractHolidayCalendar):
    # SIX Swiss Exchange (Zurich)
    rules = [
        Holiday("NewYearsDay", month=1, day=1), Holiday("BerchtoldsDay", month=1, day=2),
        GoodFriday, EasterMonday,
        Holiday("Ascension", month=1, day=1, offset=[Easter(), Day(39)]),
        Holiday("WhitMonday", month=1, day=1, offset=[Easter(), Day(50)]),
        Holiday("LabourDay", month=5, day=1), Holiday("NationalDay", month=8, day=1),
        Holiday("ChristmasEve", month=12, day=24), Holiday("Christmas", month=12, day=25),
        Holiday("StStephensDay", month=12, day=26), Holiday("NewYearsEve", month=12, day=31),
    ]


CALENDARS = {"NYSE": NYSECalendar(), "LSE": LSECalendar(), "XETRA": XETRACalendar(), "SIX": SIXCalendar()}


def trading_days(year, month, calendar="NYSE"):
    # the exchange's trading days in one month
    start = pd.Timestamp(year, month, 1)
    end = start + pd.offsets.MonthEnd(0)
    holidays = CALENDARS[calendar].holidays(start, end)
    return [d for d in pd.bdate_range(start, end) if d not in holidays]


def next_month(day):
    nxt = day + pd.offsets.MonthBegin(1)
    return nxt.year, nxt.month


def daily_action(today, closes_prev_month_end, closes_now, state, params, calendar="NYSE"):
    # today: date (Timestamp). closes_prev_month_end / closes_now: {"stock": x, "bond": y}.
    # state: {"open": bool, "exit_date": "YYYY-MM-DD" or None, "gap": float or None}
    # returns (action, new_state) with action "buy", "sell" or "none"
    days = trading_days(today.year, today.month, calendar)
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
            exit_day = trading_days(*next_month(today), calendar)[params["days_after"] - 1]
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


def to_account_currency(broker, amount, currency, account_currency):
    # converts an amount in `currency` into the account currency with live mid prices
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
    params = load_config("live/month_end_paper.yaml")
    markets = params["markets"]
    out_dir = os.path.join(ROOT, params["output_dir"])
    os.makedirs(out_dir, exist_ok=True)
    state_file = os.path.join(out_dir, "state.json")
    states = json.load(open(state_file)) if os.path.exists(state_file) else {}
    if "open" in states:                      # old single-market state file (S&P only)
        states = {"SPX500_USD": states}

    now = datetime.now(NEW_YORK)
    # cron runs this every hour at :35 (Mac clock is London time, and UK/US clocks change on different dates),
    # so only the run that lands between 16:30 and 16:55 New York time on a weekday does anything.
    # --now skips this check for a manual run.
    in_window = now.weekday() < 5 and now.hour == 16 and 30 <= now.minute <= 55
    if not in_window and not dry_run and "--now" not in sys.argv:
        return

    from trading.live.oanda_broker import OandaBroker
    broker = OandaBroker()
    today = pd.Timestamp(now.date())
    summary = broker.account_summary()

    lines = []
    for m in markets:
        stock, bond, calendar = m["stock"], m["bond"], m["calendar"]
        state = states.get(stock, {"open": False, "exit_date": None, "gap": None})
        prev = {"stock": last_close_of_previous_month(broker, stock, today),
                "bond": last_close_of_previous_month(broker, bond, today)}
        live = {"stock": sum(broker.price(stock)) / 2, "bond": sum(broker.price(bond)) / 2}
        action, new_state = daily_action(today, prev, live, state, params, calendar)

        # safety: the real OANDA position decides, not just the saved state
        position = broker.position(stock)
        note = ""
        units = None
        if (action == "buy" and position == 0) or dry_run:
            # trade size (worked out on every dry run too, so the sizing and currency conversion get checked)
            share = summary["balance"] / len(markets) * params["invest_fraction"]          # account currency
            price = to_account_currency(broker, live["stock"], stock.split("_")[-1], summary["currency"])
            decimals = broker.units_precision(stock)
            units = round(share / price, decimals) if decimals > 0 else int(share / price)
        if action == "buy" and position == 0:
            note = f"buy {units} units"
            if units <= 0:
                note = f"skipped: {units} units is below OANDA's minimum"
            elif not dry_run:
                broker.market_order(stock, units, stop_loss=None)
        elif action == "sell" and position != 0:
            note = f"close {position} units"
            if not dry_run:
                broker.close_position(stock)
        elif action != "none":
            note = f"skipped: {action} but OANDA position is {position}"

        gap = (live["stock"] / prev["stock"] - 1) - (live["bond"] / prev["bond"] - 1)
        line = {"time_ny": now.strftime("%Y-%m-%d %H:%M"), "market": stock, "action": action, "note": note,
                "stock": live["stock"], "bond": live["bond"], "gap_mtd_pct": round(100 * gap, 2),
                "position_before": position, "exit_date": new_state.get("exit_date"), "dry_run": dry_run}
        if dry_run:
            line["size_if_bought"] = units
        print(line)
        lines.append(line)
        states[stock] = new_state

    if not dry_run:
        json.dump(states, open(state_file, "w"))
        log_file = os.path.join(out_dir, "log.csv")
        pd.DataFrame(lines).to_csv(log_file, mode="a", header=not os.path.exists(log_file), index=False)


if __name__ == "__main__":
    main()
