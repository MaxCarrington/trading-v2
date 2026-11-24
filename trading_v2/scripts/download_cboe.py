# Downloads free Cboe index histories (VIX family and option strategy benchmarks) into data/cboe/.
#   env PYTHONPATH=src python scripts/download_cboe.py            (VIX family + PUT + BXM)
#   env PYTHONPATH=src python scripts/download_cboe.py BXY CLL    (any other Cboe index names)
# Each file is saved as data/cboe/<NAME>_History.csv. If a download fails, the script says where to get
# the file by hand: open the index's page on cboe.com, download its historical data CSV, and save it under the
# same name in data/cboe/.
import os
import sys
import urllib.request
import pandas as pd
import trading.utils.constants as constants

NAMES = sys.argv[1:] or ["VIX", "VIX9D", "VIX3M", "PUT", "BXM"]
URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/{name}_History.csv"

out_dir = os.path.join(constants.DATA_DIR, "cboe")
os.makedirs(out_dir, exist_ok=True)
for name in NAMES:
    path = os.path.join(out_dir, f"{name}_History.csv")
    try:
        request = urllib.request.Request(URL.format(name=name), headers={"User-Agent": "Mozilla/5.0"})
        data = urllib.request.urlopen(request, timeout=30).read()
        open(path, "wb").write(data)
        df = pd.read_csv(path)
        print(f"{name}: {len(df)} rows, {df.iloc[0, 0]} to {df.iloc[-1, 0]}, columns {list(df.columns)}")
    except Exception as e:
        print(f"{name}: download FAILED ({e}). Get it by hand from https://www.cboe.com/us/indices/dashboard/{name}/ "
              f"(historical data) and save it as {path}")
