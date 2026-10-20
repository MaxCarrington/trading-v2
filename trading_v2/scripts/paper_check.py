# Read-only check of the OANDA practice account. Places NO orders.
# Run: PYTHONPATH=src python scripts/paper_check.py
from trading.live.oanda_broker import OandaBroker

PAIR = "USD_JPY"

broker = OandaBroker()
print("Account:", broker.account_id)

summary = broker.account_summary()
for key, value in summary.items():
    print(f"  {key}: {value}")

print(f"\n{PAIR} position (units):", broker.position(PAIR))
print(f"{PAIR} pending orders:", len(broker.pending_orders(PAIR)))

candles = broker.candles(PAIR, count=6)
print(f"\nLast completed H1 candles (time is UTC):")
print(candles[["Time", "BidClose", "AskClose", "MidClose", "SpreadClose"]].to_string(index=False))
