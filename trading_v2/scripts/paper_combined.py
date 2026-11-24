# Paper bot, version 2 (switched on 14 Nov 2026 on Max's instruction). The previous version is kept as
# scripts/paper_combined_v1.py (imported below for its unchanged steps) and backed up as
# scripts/paper_combined_backup_2026-11-14.py. Same rules, sizes, books, config and crontab line as v1; one change:
#
# Markets that are SHUT at the 16:50 New York decision (OANDA hours: DE30, EU50, FR40, CH20 and NL25 close 21:59
# Frankfurt/Paris = 20:59 UK; UK100 20:59 London; AU200 and HK33 are in their overnight break; only the US indices
# and JP225 are open) can't take v1's fill-or-kill MARKET order, so v1 logs "ORDER NOT FILLED" and those trades
# never happen. v2 asks OANDA whether the market is tradeable (pricing "tradeable" flag):
#   - open: same as v1 (MARKET order now, then the books' stop orders).
#   - shut: a LIMIT order priced 5% through the market, good for 120 hours (weekends and holidays), which fills at the reopening price
#     (the "next open" fill that H341 tested). Entries AND exits work this way. The order is recorded in
#     books["_pending"]; every hourly cron run checks it: when it has filled, the entry price is set to the fill
#     and the new book's stop order is placed; if it expired unfilled (market opened more than 5% away), the
#     books go back to what they were and a warning is logged, so the next 16:50 run decides again.
#
#   env PYTHONPATH=src python scripts/paper_combined.py            (cron, hourly at :50: checks waiting orders every run,
#                                                                  decides only 16:45-16:58 New York)
#   env PYTHONPATH=src python scripts/paper_combined.py --dry-run  (prints what it would do, sends and saves nothing)
#   env PYTHONPATH=src python scripts/paper_combined.py --now      (real decision run now, outside the time window)
#
# 17 Nov 2026 (Max's request): before the decision run, a connection check (internet -> OANDA host -> token/account)
# is written to results/paper_combined/connection_log.csv. If it fails, it is retried every 45 s until 16:56 New York;
# if it never passes, the decision is skipped and that is logged. A crash during the decision run is logged there too.
# Backup of the previous version: scripts/paper_combined_backup_2026-11-17.py.
import os
import sys
import json
import time
import socket
import pandas as pd
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paper_combined_v1 as v1                                                  # noqa: E402
from paper_month_end import to_account_currency                                 # noqa: E402
from trading.utils.config import load_config                                    # noqa: E402

ROOT, NEW_YORK = v1.ROOT, v1.NEW_YORK
EMPTY = {"side": 0, "units": 0, "entry_date": None, "entry_price": None, "stop_price": None, "stop_id": None}


def reconcile_pending(broker, books, time_ny):
    # orders sent to shut markets: book their fills (and place the new books' stops) or undo them if they expired
    lines = []
    for pair, p in list(books.get("_pending", {}).items()):
        s = broker.order_state(p["order_id"])
        if s["state"] == "PENDING":
            continue
        if s["state"] == "FILLED":
            lines.append({"time_ny": time_ny, "strategy": "account", "market": pair, "action": "filled at reopen",
                          "units": p["units"], "price": s["fill_price"], "fill_time": s["fill_time"]})
            for strategy in p["opening"]:
                b = books[strategy][pair]
                b["entry_price"] = s["fill_price"]
                b["stop_id"] = broker.exit_stop_order(pair, -b["units"], b["stop_price"], broker.price_precision(pair))
                if b["stop_id"] is None:
                    lines.append({"time_ny": time_ny, "strategy": strategy, "market": pair, "action": "warning",
                                  "note": "OANDA refused the stop order: this book has NO stop"})
        else:
            for strategy, old in p["prev"].items():
                had_stop = bool(old.get("stop_id"))
                books[strategy][pair] = {**old, "stop_id": None} if strategy in p["closing"] else old
                if strategy in p["closing"] and had_stop:
                    lines.append({"time_ny": time_ny, "strategy": strategy, "market": pair, "action": "warning",
                                  "note": "exit order expired unfilled; book kept, its stop was cancelled: NO stop"})
            lines.append({"time_ny": time_ny, "strategy": "account", "market": pair, "action": "warning",
                          "note": f"next-open order {p['order_id']} {s['state']}: books restored, decided again next run"})
        del books["_pending"][pair]
    return books, lines


def run(broker, now, cfg, books, dry_run=False):
    # v1's steps 1-3 (stops filled, decisions, new books) unchanged; step 4 sends orders to shut markets for the open
    today = pd.Timestamp(now.date())
    time_ny = now.strftime("%Y-%m-%d %H:%M")
    books.setdefault("_pending", {})
    pending_pairs = set(books["_pending"])
    snapshot = {s: {k: dict(v) for k, v in books.get(s, {}).items()} for s in ("month_end", "rsi2")}

    # v1.run does steps 1-4; we stop it at step 4 by passing a broker wrapper that records orders instead of sending
    recorder = _OrderRecorder(broker)
    books_after, lines = v1.run(recorder, now, cfg, books, dry_run=True)        # dry_run=True: v1 sends nothing
    lines = [ln for ln in lines if ln.get("action") != "order"                  # v1's order lines are replaced below
             and not (ln.get("market") in pending_pairs and ln.get("note") == "OANDA position is not the sum of the books")]
    # (while an order waits for the reopen, the books already include it but the position doesn't yet: expected)
    me, r2 = cfg["month_end"], cfg["rsi2"]
    pairs = sorted({m["stock"] for m in me["markets"]} | set(r2["symbols"]))
    for pair in pairs:
        if pair in pending_pairs:
            # an order for this market is still waiting for the reopen: keep yesterday's books, decide again next run
            for s in ("month_end", "rsi2"):
                if pair in snapshot[s]:
                    books_after[s][pair] = snapshot[s][pair]
            lines.append({"time_ny": time_ny, "strategy": "account", "market": pair, "action": "note",
                          "note": "previous next-open order still pending: no new decision for this market"})
            continue
        opening = [s for s in ("month_end", "rsi2") if pair in books_after[s] and books_after[s][pair].get("side")
                   and books_after[s][pair].get("entry_date") == str(today.date()) and not books_after[s][pair].get("stop_id")]
        closing = [s for s in ("month_end", "rsi2") if pair in snapshot[s] and snapshot[s][pair].get("side")
                   and not books_after[s][pair].get("side")]
        target = sum(books_after[s][pair]["units"] for s in ("month_end", "rsi2") if pair in books_after[s])
        position = broker.position(pair)
        decimals = broker.units_precision(pair)
        order = round(target - position, decimals) if decimals > 0 else int(round(target - position))
        if not opening and not closing:
            continue                    # nothing to trade (v1's lines already warn if the position doesn't match)
        if not dry_run:
            for s in closing:                                                   # cancel the closing books' stops
                if snapshot[s][pair].get("stop_id"):
                    broker.cancel_order(snapshot[s][pair]["stop_id"])
        open_now = broker.is_tradeable(pair)
        line = {"time_ny": time_ny, "strategy": "account", "market": pair, "action": "order" if open_now else "order at next open",
                "position_before": position, "target": target, "units": order}
        if not order or dry_run:
            lines.append(line)
            continue
        if open_now:
            response = broker.market_order(pair, order, stop_loss=None)
            fill = response.get("orderFillTransaction")
            if fill is None:
                line["note"] = "ORDER NOT FILLED: " + str(response.get("orderCancelTransaction", {}).get("reason"))
                for s in ("month_end", "rsi2"):
                    if pair in snapshot[s]:
                        books_after[s][pair] = snapshot[s][pair]
                lines.append(line)
                continue
            line["price"] = float(fill["price"])
            for s in opening:
                b = books_after[s][pair]
                b["entry_price"] = float(fill["price"])
                b["stop_id"] = broker.exit_stop_order(pair, -b["units"], b["stop_price"], broker.price_precision(pair))
        else:
            ref = sum(broker.price(pair)) / 2
            oid = broker.next_open_order(pair, order, ref, broker.price_precision(pair))
            if oid is None:
                line["note"] = "OANDA refused the next-open order: books kept"
                for s in ("month_end", "rsi2"):
                    if pair in snapshot[s]:
                        books_after[s][pair] = snapshot[s][pair]
            else:
                line["order_id"] = oid
                books_after["_pending"][pair] = {"order_id": oid, "units": order, "opening": opening, "closing": closing,
                                                 "prev": {s: snapshot[s][pair] for s in ("month_end", "rsi2") if pair in snapshot[s]},
                                                 "placed": time_ny}
        lines.append(line)
    return books_after, lines


class _OrderRecorder:
    # passes reads through to the real broker; v1.run is called with dry_run=True so it never sends orders
    def __init__(self, broker):
        self._b = broker

    def __getattr__(self, name):
        return getattr(self._b, name)


OANDA_HOST = {"practice": "api-fxpractice.oanda.com", "live": "api-fxtrade.oanda.com"}
CHECK_EVERY_S, CHECK_DEADLINE = 45, (16, 56)          # retry every 45 s, last try by 16:56 New York


def _probe():
    # one connection check: (ok, stage, detail, broker). Stages: internet/DNS, HTTPS to OANDA, token + account
    import requests
    from trading.live.oanda_broker import OandaBroker
    host = OANDA_HOST.get(os.environ.get("OANDA_ENVIRONMENT", "practice"), OANDA_HOST["practice"])
    try:
        socket.getaddrinfo(host, 443)
    except OSError as e:
        return False, "DNS", f"can't resolve {host} (no internet?): {e}", None
    try:
        r = requests.get(f"https://{host}/v3/accounts", timeout=10)     # no token: any HTTP reply proves the link works
        http = r.status_code
    except requests.RequestException as e:
        return False, "HTTPS", f"{host} not reachable: {type(e).__name__}", None
    try:
        broker = OandaBroker()
        summary = broker.account_summary()
        return True, "account", f"OANDA reachable (HTTP {http} without token, as expected); account OK, balance {float(summary['balance']):,.2f} {summary['currency']}", broker
    except Exception as e:
        code = getattr(e, "code", None)
        return False, "account", f"OANDA reachable (HTTP {http}); OANDA refused the account request: {code or type(e).__name__} {str(e)[:150]}", None


def connection_check(out_dir, live, now_fn=lambda: datetime.now(NEW_YORK), sleep=time.sleep):
    # retries until it passes or the deadline; every attempt is written to connection_log.csv (live runs only)
    attempt = 0
    while True:
        attempt += 1
        ok, stage, detail, broker = _probe()
        _connection_log(out_dir, live, now_fn(), attempt, "OK" if ok else "FAIL", stage, detail)
        if ok:
            return broker
        start = now_fn()
        in_window = start.hour == 16 and start.minute >= 45
        nxt = start + pd.Timedelta(seconds=CHECK_EVERY_S)
        if in_window and (nxt.hour, nxt.minute) > CHECK_DEADLINE:
            _connection_log(out_dir, live, now_fn(), attempt, "GAVE UP", stage, "no connection by 16:56 New York: today's decision skipped")
            return None
        if not in_window and attempt >= 3:                 # --now / --dry-run outside the window: 3 tries
            _connection_log(out_dir, live, now_fn(), attempt, "GAVE UP", stage, "3 failed checks (run outside the 16:45-16:58 window)")
            return None
        sleep(CHECK_EVERY_S)


def _connection_log(out_dir, live, now, attempt, status, stage, detail):
    row = {"time_ny": now.strftime("%Y-%m-%d %H:%M:%S"), "attempt": attempt, "status": status, "stage": stage, "detail": detail}
    print("connection check:", row, flush=True)
    if live:
        path = os.path.join(out_dir, "connection_log.csv")
        pd.DataFrame([row]).to_csv(path, mode="a", header=not os.path.exists(path), index=False)


def main():
    dry_run = "--dry-run" in sys.argv
    live = not dry_run
    cfg = load_config("live/combined_paper.yaml")
    out_dir = os.path.join(ROOT, cfg["output_dir"])
    state_file = os.path.join(out_dir, "books.json")
    books = json.load(open(state_file)) if os.path.exists(state_file) else {}
    now = datetime.now(NEW_YORK)

    from trading.live.oanda_broker import OandaBroker
    lines = []
    if books.get("_pending") and live:
        broker = OandaBroker()
        books, lines = reconcile_pending(broker, books, now.strftime("%Y-%m-%d %H:%M"))
    in_window = now.weekday() < 5 and now.hour == 16 and 45 <= now.minute <= 58
    if (in_window or dry_run or "--now" in sys.argv) and (books.get("_last_run") != str(now.date()) or dry_run):
        broker = connection_check(out_dir, live)
        if broker is not None:
            broker.check_token()
            try:
                books, more = run(broker, now, cfg, books, dry_run)
            except Exception as e:
                _connection_log(out_dir, live, datetime.now(NEW_YORK), 0, "RUN FAILED", "decision run",
                                f"{type(e).__name__}: {str(e)[:200]} (no decision today; see cron.log)")
                raise
            lines += more
            if live:
                books["_last_run"] = str(now.date())
    for line in lines:
        print(line)
    if live and lines:
        json.dump(books, open(state_file, "w"), indent=1)
        log_file = os.path.join(out_dir, "log.csv")
        old = pd.read_csv(log_file) if os.path.exists(log_file) else pd.DataFrame()
        pd.concat([old, pd.DataFrame(lines)], ignore_index=True).to_csv(log_file, index=False)


if __name__ == "__main__":
    main()
