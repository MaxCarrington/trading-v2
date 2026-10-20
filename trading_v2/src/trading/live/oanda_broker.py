# Small wrapper around the OANDA v20 API for paper trading.
# Practice account only: it refuses to start if OANDA_ENVIRONMENT is not "practice".
import os
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from oandapyV20 import API
import oandapyV20.endpoints.accounts as accounts
import oandapyV20.endpoints.instruments as instruments
import oandapyV20.endpoints.orders as orders
import oandapyV20.endpoints.positions as positions
import oandapyV20.endpoints.pricing as pricing

from trading.data.data_gathering.OANDA import candles_to_df

load_dotenv()


def price_format(pair):
    # OANDA rejects prices with too many decimals: 3 for JPY pairs, 5 for the rest
    return "{:.3f}" if "JPY" in pair else "{:.5f}"


class OandaBroker:
    def __init__(self):
        environment = os.environ.get("OANDA_ENVIRONMENT", "practice")
        if environment != "practice":
            raise RuntimeError("OandaBroker only runs on the practice account (OANDA_ENVIRONMENT=practice)")

        self.client = API(access_token=os.environ["OANDA_API_TOKEN"], environment=environment)
        self.account_id = os.environ.get("OANDA_ACCOUNT_ID") or self._only_account()

    def _only_account(self):
        # if OANDA_ACCOUNT_ID is not in .env, use the account when there is exactly one
        response = self.client.request(accounts.AccountList())
        ids = [a["id"] for a in response["accounts"]]
        if len(ids) != 1:
            raise RuntimeError(f"Found {len(ids)} accounts, add OANDA_ACCOUNT_ID to .env")
        return ids[0]

    # ---------- reading ----------

    def account_summary(self):
        response = self.client.request(accounts.AccountSummary(self.account_id))
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
        response = self.client.request(positions.OpenPositions(self.account_id))
        for p in response["positions"]:
            if p["instrument"] == pair:
                return int(p["long"]["units"]) + int(p["short"]["units"])
        return 0

    def candles(self, pair, count=24 * 40, granularity="H1"):
        # completed candles only, with Bid/Ask/Mid columns like the downloaded CSVs
        params = {"count": count, "granularity": granularity, "price": "BAM"}
        response = self.client.request(instruments.InstrumentsCandles(pair, params=params))
        df = candles_to_df(response["candles"])
        price_cols = [c for c in df.columns if c not in ("Time", "Volume")]
        df[price_cols] = df[price_cols].astype(float)     # OANDA sends prices as text
        return df

    def price(self, pair):
        # live bid and ask right now
        response = self.client.request(pricing.PricingInfo(self.account_id, params={"instruments": pair}))
        p = response["prices"][0]
        return float(p["bids"][0]["price"]), float(p["asks"][0]["price"])

    def pending_orders(self, pair):
        response = self.client.request(orders.OrdersPending(self.account_id))
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
        return self.client.request(orders.OrderCreate(self.account_id, data=data))

    def market_order(self, pair, units, stop_loss):
        # used when price is already past the entry level (the backtest fills these at the bar's open)
        fmt = price_format(pair)
        data = {"order": {
            "type": "MARKET",
            "instrument": pair,
            "units": str(int(units)),
            "timeInForce": "FOK",
            "positionFill": "DEFAULT",
            "stopLossOnFill": {"price": fmt.format(stop_loss), "timeInForce": "GTC"},
        }}
        return self.client.request(orders.OrderCreate(self.account_id, data=data))

    def cancel_pending(self, pair):
        for o in self.pending_orders(pair):
            # stop losses attached to open trades are left alone
            if o["type"] in ("STOP", "LIMIT", "MARKET_IF_TOUCHED"):
                self.client.request(orders.OrderCancel(self.account_id, o["id"]))

    def close_position(self, pair):
        units = self.position(pair)
        if units > 0:
            data = {"longUnits": "ALL"}
        elif units < 0:
            data = {"shortUnits": "ALL"}
        else:
            return None
        return self.client.request(positions.PositionClose(self.account_id, pair, data=data))
