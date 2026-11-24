# Small wrapper around the OANDA v20 API for paper trading.
# Practice account only: it refuses to start if OANDA_ENVIRONMENT is not "practice".
import os
import time
import uuid
import hashlib
from datetime import datetime, timedelta, timezone

import requests

from dotenv import load_dotenv
from oandapyV20 import API
from oandapyV20.exceptions import V20Error
import oandapyV20.endpoints.accounts as accounts
import oandapyV20.endpoints.instruments as instruments
import oandapyV20.endpoints.orders as orders
import oandapyV20.endpoints.positions as positions
import oandapyV20.endpoints.pricing as pricing
import oandapyV20.endpoints.transactions as transactions

from trading.data.data_gathering.OANDA import candles_to_df

load_dotenv()

REQUEST_TIMEOUT_S = 20      # one OANDA request gives up after 20 s
RETRY_TRIES = 3             # tries per request
RETRY_WAIT_S = 15           # wait between tries
RETRY_BUDGET_S = 180        # at most 3 minutes of retry waiting per run, so a 16:50 run ends inside the window


def _describe(e):
    if isinstance(e, V20Error):
        return f"HTTP {e.code} {str(e.msg)[:120]}"
    return type(e).__name__


def _retryable_read(e):
    if isinstance(e, V20Error):
        return e.code in (401, 429) or e.code >= 500
    return isinstance(e, (requests.exceptions.Timeout, requests.exceptions.ConnectionError))


def _refused_before_accepting(e):
    # OANDA turned the request away at the door (not authorised / too many requests): nothing was created
    return isinstance(e, V20Error) and e.code in (401, 429)


def _ambiguous(e):
    # the order may or may not have been accepted
    return (isinstance(e, V20Error) and e.code >= 500) or isinstance(e, (requests.exceptions.Timeout, requests.exceptions.ConnectionError))


def _rebuild_response(broker, order):
    # an OrderCreate-like response from the order's current state, for callers that lost the real reply
    out = {"orderCreateTransaction": {"id": order["id"], "lookedUp": True}}
    if order["state"] == "FILLED" and order.get("fillingTransactionID"):
        t = broker._read(lambda: transactions.TransactionDetails(broker.account_id, order["fillingTransactionID"]), "fill lookup")
        out["orderFillTransaction"] = t["transaction"]
    elif order["state"] == "CANCELLED":
        out["orderCancelTransaction"] = {"reason": order.get("cancelledReason", "CANCELLED")}
    return out


def price_format(pair):
    # OANDA rejects prices with too many decimals: 3 for JPY pairs, 5 for the rest
    return "{:.3f}" if "JPY" in pair else "{:.5f}"


class OandaBroker:
    def __init__(self):
        environment = os.environ.get("OANDA_ENVIRONMENT", "practice")
        if environment != "practice":
            raise RuntimeError("OandaBroker only runs on the practice account (OANDA_ENVIRONMENT=practice)")

        self.client = API(access_token=os.environ["OANDA_API_TOKEN"], environment=environment,
                          request_params={"timeout": REQUEST_TIMEOUT_S})
        self.retry_budget_s = RETRY_BUDGET_S          # total waiting allowed for retries in one run
        self.account_id = os.environ.get("OANDA_ACCOUNT_ID") or self._only_account()

    # ---------- added 17 Nov 2026 (Max: "yes retry"): one rejected or failed request no longer kills a run ----------
    # (backup of the file before this change: oanda_broker_backup_2026-11-17.py)
    # Reads are retried on 401 / 429 / 5xx, timeouts and connection errors. Orders are retried ONLY when OANDA clearly
    # refused them before accepting (401 / 429); after a timeout, connection error or 5xx the order may have gone
    # through, so the bot first looks it up by its client id and never sends it twice.

    def _wait(self, what, attempt, err):
        wait = min(RETRY_WAIT_S, self.retry_budget_s)
        print(f"{datetime.now():%Y-%m-%d %H:%M:%S} OANDA retry: {what} attempt {attempt}/{RETRY_TRIES} failed ({_describe(err)}); "
              f"{'waiting %ds' % wait if wait > 0 else 'no retry time left this run'}", flush=True)
        if wait <= 0:
            return False
        time.sleep(wait)
        self.retry_budget_s -= wait
        return True

    def _read(self, make_endpoint, what):
        # make_endpoint() builds a fresh endpoint each try (an endpoint object holds its last response)
        for attempt in range(1, RETRY_TRIES + 1):
            try:
                return self.client.request(make_endpoint())
            except Exception as e:
                if not _retryable_read(e) or attempt == RETRY_TRIES or not self._wait(what, attempt, e):
                    raise

    def _create_order(self, data, what):
        # sends an order with a unique client id; returns OANDA's response (or an equivalent one rebuilt from the
        # order's state if the reply was lost). Never sends the same order twice.
        cid = "bot-" + uuid.uuid4().hex[:20]
        data["order"]["clientExtensions"] = {"id": cid}
        for attempt in range(1, RETRY_TRIES + 1):
            try:
                return self.client.request(orders.OrderCreate(self.account_id, data=data))
            except Exception as e:
                if _refused_before_accepting(e):
                    if attempt == RETRY_TRIES or not self._wait(what, attempt, e):
                        raise
                    continue
                if not _ambiguous(e):
                    raise
                print(f"{datetime.now():%Y-%m-%d %H:%M:%S} OANDA order {what}: no clear answer ({_describe(e)}); "
                      f"looking it up by client id {cid} before doing anything else", flush=True)
                found = self._lookup_order(cid)
                if found is not None:
                    print(f"{datetime.now():%Y-%m-%d %H:%M:%S} OANDA order {what}: it DID reach OANDA (state {found['order']['state']}); not resending", flush=True)
                    return _rebuild_response(self, found["order"])
                print(f"{datetime.now():%Y-%m-%d %H:%M:%S} OANDA order {what}: OANDA has no such order, so it never arrived", flush=True)
                if attempt == RETRY_TRIES or not self._wait(what, attempt, e):
                    raise

    def _lookup_order(self, cid):
        # the order with this client id, or None if OANDA has none (a lookup failure is raised: then we don't resend)
        try:
            return self._read(lambda: orders.OrderDetails(self.account_id, f"@{cid}"), "order lookup")
        except V20Error as e:
            if e.code == 404:
                return None
            raise

    def _only_account(self):
        # if OANDA_ACCOUNT_ID is not in .env, use the account when there is exactly one
        response = self._read(lambda: accounts.AccountList(), "account list")
        ids = [a["id"] for a in response["accounts"]]
        if len(ids) != 1:
            raise RuntimeError(f"Found {len(ids)} accounts, add OANDA_ACCOUNT_ID to .env")
        return ids[0]

    def check_token(self, tries=3, wait=60):
        # read-only first call of a run. OANDA has answered 401 at some cron runs although the same token works
        # minutes later, so try again a few times and log which token went out (a short hash, never the token)
        for attempt in range(1, tries + 1):
            try:
                self.client.request(accounts.AccountSummary(self.account_id))
                return
            except V20Error as e:
                token = os.environ["OANDA_API_TOKEN"]
                print(f"{datetime.now():%Y-%m-%d %H:%M:%S} OANDA check {attempt}/{tries} failed: {e.code} {e.msg} | "
                      f"token {hashlib.sha256(token.encode()).hexdigest()[:6]} length {len(token)}", flush=True)
                if e.code != 401 or attempt == tries:
                    raise
                time.sleep(wait)

    # ---------- reading ----------

    def account_summary(self):
        response = self._read(lambda: accounts.AccountSummary(self.account_id), "account summary")
        a = response["account"]
        return {
            "currency": a["currency"],
            "balance": float(a["balance"]),
            "nav": float(a["NAV"]),
            "margin_available": float(a["marginAvailable"]),
            "open_trades": int(a["openTradeCount"]),
            "pending_orders": int(a["pendingOrderCount"]),
        }

    def position(self, pair):
        # net units: + long, - short, 0 flat
        response = self._read(lambda: positions.OpenPositions(self.account_id), "open positions")
        for p in response["positions"]:
            if p["instrument"] == pair:
                return float(p["long"]["units"]) + float(p["short"]["units"])   # index CFDs can have fractional units
        return 0

    def candles(self, pair, count=24 * 40, granularity="H1"):
        # completed candles only, with Bid/Ask/Mid columns like the downloaded CSVs
        params = {"count": count, "granularity": granularity, "price": "BAM"}
        response = self._read(lambda: instruments.InstrumentsCandles(pair, params=params), f"candles {pair}")
        df = candles_to_df(response["candles"])
        price_cols = [c for c in df.columns if c not in ("Time", "Volume")]
        df[price_cols] = df[price_cols].astype(float)     # OANDA sends prices as text
        return df

    def price(self, pair):
        # live bid and ask right now
        response = self._read(lambda: pricing.PricingInfo(self.account_id, params={"instruments": pair}), f"price {pair}")
        p = response["prices"][0]
        return float(p["bids"][0]["price"]), float(p["asks"][0]["price"])

    def units_precision(self, pair):
        # how many decimals OANDA accepts for this instrument's units (0 for FX, often 1 for index CFDs)
        response = self._read(lambda: accounts.AccountInstruments(self.account_id, params={"instruments": pair}), f"instrument {pair}")
        return int(response["instruments"][0]["tradeUnitsPrecision"])

    def price_precision(self, pair):
        # how many decimals OANDA accepts for this instrument's prices (e.g. 1 for SPX500_USD, 5 for EUR_USD)
        response = self._read(lambda: accounts.AccountInstruments(self.account_id, params={"instruments": pair}), f"instrument {pair}")
        return int(response["instruments"][0]["displayPrecision"])

    def today_bar(self, pair):
        # today's daily bar so far (OANDA's day runs 17:00 to 17:00 New York): mid open, high, low, close
        params = {"count": 2, "granularity": "D", "price": "M"}
        response = self._read(lambda: instruments.InstrumentsCandles(pair, params=params), f"today bar {pair}")
        last = response["candles"][-1]
        if last.get("complete"):
            mid = sum(self.price(pair)) / 2         # no bar for today yet: use the live price
            return mid, mid, mid, mid
        m = last["mid"]
        return float(m["o"]), float(m["h"]), float(m["l"]), float(m["c"])

    def order_state(self, order_id):
        # "PENDING", "FILLED", "CANCELLED" or "TRIGGERED", with the fill price and time when it filled
        order = self._read(lambda: orders.OrderDetails(self.account_id, str(order_id)), f"order {order_id}")["order"]
        out = {"state": order["state"], "fill_price": None, "fill_time": order.get("filledTime")}
        if order["state"] == "FILLED" and order.get("fillingTransactionID"):
            t = self._read(lambda: transactions.TransactionDetails(self.account_id, order["fillingTransactionID"]), "fill details")
            out["fill_price"] = float(t["transaction"].get("price", "nan"))
        return out

    def pending_orders(self, pair):
        response = self._read(lambda: orders.OrdersPending(self.account_id), "pending orders")
        return [o for o in response["orders"] if o.get("instrument") == pair]

    # ---------- trading ----------

    def stop_order(self, pair, units, price, stop_loss, minutes=65):
        # entry stop order with a stop loss attached; it expires after `minutes`
        # so an old order can never fill if the bot stops running
        fmt = price_format(pair)
        expiry = datetime.now(timezone.utc) + timedelta(minutes=minutes)
        data = {"order": {
            "type": "STOP",
            "instrument": pair,
            "units": str(int(units)),
            "price": fmt.format(price),
            "timeInForce": "GTD",
            "gtdTime": expiry.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "positionFill": "DEFAULT",
            "stopLossOnFill": {"price": fmt.format(stop_loss), "timeInForce": "GTC"},
        }}
        return self._create_order(data, f"entry stop {pair}")

    def market_order(self, pair, units, stop_loss=None):
        # used when price is already past the entry level (the backtest fills these at the bar's open)
        # stop_loss=None sends the order without a stop loss (the month-end trade has none)
        fmt = price_format(pair)
        data = {"order": {
            "type": "MARKET",
            "instrument": pair,
            "units": str(units if isinstance(units, float) else int(units)),
            "timeInForce": "FOK",
            "positionFill": "DEFAULT",
        }}
        if stop_loss is not None:
            data["order"]["stopLossOnFill"] = {"price": fmt.format(stop_loss), "timeInForce": "GTC"}
        return self._create_order(data, f"market {pair} {units}")

    def exit_stop_order(self, pair, units, price, decimals):
        # a stand-alone stop order that stays until filled or cancelled (GTC). In a netting account it adds `units`
        # to the position when price trades through `price`, so it can close one strategy's share of a market
        # while another strategy holds the rest. Returns the order id, or None if OANDA refused it.
        data = {"order": {
            "type": "STOP",
            "instrument": pair,
            "units": str(units if isinstance(units, float) else int(units)),
            "price": f"{price:.{decimals}f}",
            "timeInForce": "GTC",
            "positionFill": "DEFAULT",
        }}
        response = self._create_order(data, f"exit stop {pair}")
        if "orderCreateTransaction" not in response or "orderCancelTransaction" in response:
            return None
        return response["orderCreateTransaction"]["id"]

    def cancel_order(self, order_id):
        # cancels one order; returns False if it was already filled or cancelled
        for attempt in range(1, RETRY_TRIES + 1):
            try:
                self.client.request(orders.OrderCancel(self.account_id, str(order_id)))
                return True
            except Exception as e:
                if _refused_before_accepting(e) and attempt < RETRY_TRIES and self._wait(f"cancel {order_id}", attempt, e):
                    continue
                if _ambiguous(e):
                    try:                                    # did the cancel go through? (cancelling twice is harmless anyway)
                        return self.order_state(order_id)["state"] == "CANCELLED"
                    except Exception:
                        return False
                return False

    def cancel_pending(self, pair):
        for o in self.pending_orders(pair):
            # stop losses attached to open trades are left alone
            if o["type"] in ("STOP", "LIMIT", "MARKET_IF_TOUCHED"):
                self.cancel_order(o["id"])

    def close_position(self, pair):
        units = self.position(pair)
        if units > 0:
            data = {"longUnits": "ALL"}
        elif units < 0:
            data = {"shortUnits": "ALL"}
        else:
            return None
        for attempt in range(1, RETRY_TRIES + 1):
            try:
                return self.client.request(positions.PositionClose(self.account_id, pair, data=data))
            except Exception as e:
                if _refused_before_accepting(e) and attempt < RETRY_TRIES and self._wait(f"close {pair}", attempt, e):
                    continue
                if _ambiguous(e) and self.position(pair) == 0:     # it did close: don't send again
                    return {"note": "position confirmed closed after an unclear reply"}
                raise

    # ---------- added 14 Nov 2026: orders for markets that are shut at the bot's 16:50 New York run ----------
    # (backup of the file before this change: oanda_broker_backup_2026-11-14.py)

    def is_tradeable(self, pair):
        # OANDA's own flag from the pricing endpoint: False while the market is shut
        response = self._read(lambda: pricing.PricingInfo(self.account_id, params={"instruments": pair}), f"tradeable {pair}")
        return bool(response["prices"][0].get("tradeable", False))

    def next_open_order(self, pair, units, ref_price, decimals, hours=120, far_pct=5.0):
        # A LIMIT order priced far through the market (buy limit 5% above the last price, sell limit 5% below) fills
        # at the best price available when the market reopens, i.e. about the opening price, unless the market
        # opens more than 5% away. OANDA accepts entry orders while a market is shut. It expires after `hours`
        # (120 h covers a weekend plus holidays, e.g. Easter). Returns the order id, or None if OANDA refused it.
        price = ref_price * (1 + far_pct / 100) if units > 0 else ref_price * (1 - far_pct / 100)
        expiry = datetime.now(timezone.utc) + timedelta(hours=hours)
        data = {"order": {
            "type": "LIMIT",
            "instrument": pair,
            "units": str(units if isinstance(units, float) else int(units)),
            "price": f"{price:.{decimals}f}",
            "timeInForce": "GTD",
            "gtdTime": expiry.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "positionFill": "DEFAULT",
        }}
        response = self._create_order(data, f"next-open {pair}")
        if "orderCreateTransaction" not in response or "orderCancelTransaction" in response:
            return None
        return response["orderCreateTransaction"]["id"]
