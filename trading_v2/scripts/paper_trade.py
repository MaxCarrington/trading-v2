# Paper trades London Breakout v1.5 on the OANDA practice account, one step per H1 bar.
#
# Every hour, a few seconds after the bar closes:
#   1. fetch the completed H1 bar (bid/ask/mid) from OANDA
#   2. cancel last hour's entry orders and read the real position and balance
#   3. call the SAME strategy function the backtest uses, with that bar
#   4. turn its orders into OANDA orders:
#      - flat + entry stop -> stop order at the level, stop loss on the other side of the range (expires in 65 min)
#      - in a trade + exit -> close the position at market
#      - in a trade + protective stop -> nothing to do, the stop loss is already on OANDA
#
# The strategy's memory (store) is saved after every bar, so the bot can be stopped and started again.
# Logs: results/paper_trading/log.csv (one line per bar) and trades.csv (the strategy's own trade list).
#
# Run (keeps the Mac awake):  caffeinate -i env PYTHONPATH=src python scripts/paper_trade.py
# Stop with Ctrl+C. Open trades keep their stop loss on OANDA while the bot is off.
import os
import sys
import time
import pickle
import pandas as pd
from datetime import datetime, timezone

from trading.utils.config import load_config
from trading.strategies.strategy_loader import get_strategy, get_params
from trading.live.oanda_broker import OandaBroker

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def to_strategy_rows(candles):
    # same columns the backtester gives the strategy: mid prices as Open/High/Low/Close, plus Bid*/Ask*
    df = candles.rename(columns={"MidOpen": "Open", "MidHigh": "High", "MidLow": "Low", "MidClose": "Close"})
    df["Spread"] = df["AskClose"] - df["BidClose"]
    return [row for _, row in df.iterrows()]


def balance_in_usd(broker):
    # the strategy sizes in USD; a GBP account is converted with the live GBP_USD price
    summary = broker.account_summary()
    if summary["currency"] == "USD":
        return summary["balance"]
    if summary["currency"] == "GBP":
        bid, ask = broker.price("GBP_USD")
        return summary["balance"] * (bid + ask) / 2
    raise RuntimeError(f"Account currency {summary['currency']} not supported")


def send_orders(broker, out, position, store, pair, max_units):
    # turns the strategy's orders into OANDA orders, returns a short description for the log
    if position != 0:
        if out["marketOrders"][0] != 0:
            broker.close_position(pair)
            return "close at market"
        return "in trade, stop loss on OANDA"

    bid, ask = broker.price(pair)
    if out["stopOrders1"][0] > 0:                                  # buy stop
        units = min(out["stopOrders1"][0], max_units)
        level, stop_loss = out["stopPrices1"][0], store["asian_low"][pair]
        if ask >= level:                                           # already above the level: buy now
            broker.market_order(pair, units, stop_loss)
            return f"buy {units} at market (ask {ask} >= {level:.3f}), SL {stop_loss:.3f}"
        response = broker.stop_order(pair, units, level, stop_loss)
        store["live_order_id"] = response["orderCreateTransaction"]["id"]
        return f"buy stop {units} at {level:.3f}, SL {stop_loss:.3f}"

    if out["stopOrders2"][0] < 0:                                  # sell stop
        units = max(out["stopOrders2"][0], -max_units)
        level, stop_loss = out["stopPrices2"][0], store["asian_high"][pair]
        if bid <= level:                                           # already below the level: sell now
            broker.market_order(pair, units, stop_loss)
            return f"sell {units} at market (bid {bid} <= {level:.3f}), SL {stop_loss:.3f}"
        response = broker.stop_order(pair, units, level, stop_loss)
        store["live_order_id"] = response["orderCreateTransaction"]["id"]
        return f"sell stop {units} at {level:.3f}, SL {stop_loss:.3f}"

    return "no orders"


def step(broker, strategy, store, row, params, pair, max_units, act=True):
    # one H1 bar: same call as the backtest, then (if act) real orders
    # last hour's entry order is gone from the pending list = it filled. If we are flat now, the stop loss
    # was also hit within the hour (can't happen in the backtest), so mark the day as traded: one trade per day
    pending_ids = [o["id"] for o in broker.pending_orders(pair)]
    if store.get("live_order_id") and store["live_order_id"] not in pending_ids:
        store["traded_today"][pair] = True
    store["live_order_id"] = None
    broker.cancel_pending(pair)
    position = broker.position(pair)
    balance = balance_in_usd(broker)
    out = strategy(store, [row], [position], {"balance": balance}, params)
    action = send_orders(broker, out, position, out["store"], pair, max_units) if act else "catch-up bar, no orders"
    return out["store"], {"logged_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                          "bar_time_utc": row["Time"], "close": row["Close"], "position": position,
                          "balance_usd": round(balance, 2), "action": action}


def warm_up(broker, strategy, params, pair, days):
    # replays recent history (flat, no orders) so the trend average and today's range are filled in
    candles = broker.candles(pair, count=min(24 * days, 5000))
    store = None
    for row in to_strategy_rows(candles):
        store = strategy(store, [row], [0], {"balance": 0}, params)["store"]
    store["trade_list"][pair] = []          # trades from the replay never happened
    return store, candles["Time"].iloc[-1]


def save(store, last_time, log_rows, out_dir, pair):
    store["ohlcv"][pair] = store["ohlcv"][pair].iloc[-500:]   # only the last bars are needed
    with open(os.path.join(out_dir, "store.pkl"), "wb") as f:
        pickle.dump({"store": store, "last_time": last_time}, f)
    log_path = os.path.join(out_dir, "log.csv")
    pd.DataFrame(log_rows).to_csv(log_path, mode="a", header=not os.path.exists(log_path), index=False)
    pd.DataFrame(store["trade_list"][pair]).to_csv(os.path.join(out_dir, "trades.csv"), index=False)


def seconds_to_next_bar(after):
    now = time.time()
    return 3600 - now % 3600 + after


def main():
    config = load_config("live/london_breakout_v1.5_paper.yaml")
    params = get_params(load_config(config["strategy_config"]))
    strategy = get_strategy(params["strategy_name"])
    if params["pairs"] != ["USD_JPY"]:
        sys.exit("Paper trading is set up for USD_JPY only")
    pair = "USD_JPY"

    out_dir = os.path.join(ROOT, config["output_dir"])
    os.makedirs(out_dir, exist_ok=True)
    broker = OandaBroker()

    store_path = os.path.join(out_dir, "store.pkl")
    if os.path.exists(store_path):
        with open(store_path, "rb") as f:
            saved = pickle.load(f)
        store, last_time = saved["store"], saved["last_time"]
        print(f"Loaded saved store, last bar {last_time} UTC")
    else:
        store, last_time = warm_up(broker, strategy, params, pair, config["warmup_days"])
        save(store, last_time, [], out_dir, pair)
        print(f"Warmed up on {config['warmup_days']} days, last bar {last_time} UTC")

    while True:
        wait = seconds_to_next_bar(config["seconds_after_close"])
        print(f"Next check in {wait / 60:.1f} min")
        time.sleep(wait)
        try:
            candles = broker.candles(pair, count=30)
            for _ in range(3):                       # the bar that just closed can take a few seconds to be marked complete
                if pd.Timestamp.utcnow().tz_localize(None) - candles["Time"].iloc[-1] < pd.Timedelta(hours=2):
                    break
                time.sleep(20)
                candles = broker.candles(pair, count=30)
            new_rows = [r for r in to_strategy_rows(candles) if r["Time"] > last_time]
            log_rows = []
            for k, row in enumerate(new_rows):
                # only the newest bar sends orders; older ones (bot was off) just update the store
                store, log = step(broker, strategy, store, row, params, pair, config["max_units"],
                                  act=(k == len(new_rows) - 1))
                log_rows.append(log)
                last_time = row["Time"]
                print(log)
            if new_rows:
                save(store, last_time, log_rows, out_dir, pair)
        except Exception as e:                       # network errors etc: log and try again next hour
            print(f"ERROR {datetime.now(timezone.utc)}: {e}")


if __name__ == "__main__":
    main()
