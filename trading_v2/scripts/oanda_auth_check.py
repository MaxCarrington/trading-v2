# Checks which OANDA settings a bot sees, without printing the token itself.
#   env PYTHONPATH=src python scripts/oanda_auth_check.py plain      (like paper_rsi2.py)
#   env PYTHONPATH=src python scripts/oanda_auth_check.py combined   (with the same imports as paper_combined.py)
#   env PYTHONPATH=src python scripts/oanda_auth_check.py main       (runs paper_combined.py --dry-run exactly, and
#                                                                     reports every OANDA call it makes)
import os
import sys
import hashlib
import runpy

HERE = os.path.dirname(os.path.abspath(__file__))
mode = sys.argv[1] if len(sys.argv) > 1 else "plain"


def short(x):
    return x[:4] + "..." + x[-4:] if len(x) > 8 else "(" + str(len(x)) + " characters)"


def fingerprint(token):
    return hashlib.sha256(token.encode()).hexdigest()[:6]


if mode == "main":
    from oandapyV20 import API
    original_request = API.request

    def request(self, endpoint):
        session = getattr(self, "client", None)
        auth = str(getattr(session, "headers", {}).get("Authorization", "")).replace("Bearer ", "")
        path = str(getattr(endpoint, "_endpoint", "?"))
        acct = os.environ.get("OANDA_ACCOUNT_ID", "")
        print("OANDA call:", type(endpoint).__name__,
              "| path", path.replace(acct, "<account from settings>") if acct else path,
              "| environment", getattr(self, "environment", "?"),
              "| token sent", fingerprint(auth), "len", len(auth),
              "| token in settings", fingerprint(os.environ.get("OANDA_API_TOKEN", "")))
        try:
            return original_request(self, endpoint)
        except Exception as e:
            print("   FAILED:", e)
            raise

    API.request = request
    sys.argv = [os.path.join(HERE, "paper_combined.py"), "--dry-run"]
    sys.path.insert(0, HERE)
    runpy.run_path(sys.argv[0], run_name="__main__")
    sys.exit()

sys.path.insert(0, HERE)
if mode == "combined":
    import paper_combined  # noqa: F401
from trading.live.oanda_broker import OandaBroker

token = os.environ.get("OANDA_API_TOKEN", "")
print("environment:", os.environ.get("OANDA_ENVIRONMENT"))
print("account in settings:", short(os.environ.get("OANDA_ACCOUNT_ID", "")))
print("token length:", len(token), " fingerprint:", fingerprint(token))
broker = OandaBroker()
print("account the bot uses:", short(broker.account_id))
try:
    print("account summary OK, currency", broker.account_summary()["currency"])
except Exception as e:
    print("account summary FAILED:", e)
