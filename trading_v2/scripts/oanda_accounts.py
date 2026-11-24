# Lists the OANDA practice accounts your token can see (account numbers only, never the token).
#   env PYTHONPATH=src python scripts/oanda_accounts.py
import os
from dotenv import load_dotenv
from oandapyV20 import API
from oandapyV20.endpoints import accounts

load_dotenv()
client = API(access_token=os.environ["OANDA_API_TOKEN"], environment=os.environ.get("OANDA_ENVIRONMENT", "practice"))
for a in client.request(accounts.AccountList())["accounts"]:
    print("account:", a["id"], "tags:", a.get("tags"))
    try:
        s = client.request(accounts.AccountSummary(a["id"]))["account"]
        print("   OK - balance", s["balance"], s["currency"], "open trades", s["openTradeCount"])
    except Exception as e:
        print("   cannot read this account:", e)
