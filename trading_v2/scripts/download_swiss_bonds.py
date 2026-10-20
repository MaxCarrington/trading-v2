# Downloads daily Swiss Confederation bond yields from the SNB data portal (data.snb.ch, cube "rendoblid")
# and saves the 10-year yield as data/long_history/CH10Y.csv (date, yield in %), the same layout as FRED's DGS10.csv.
# OANDA has no Swiss bond, so scripts/month_end_stocks_bonds.py builds a bond price from these yields.
# Run from the repo folder:  python scripts/download_swiss_bonds.py
import io
import os
import pandas as pd
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "long_history")
os.makedirs(OUT, exist_ok=True)
URL = "https://data.snb.ch/api/cube/rendoblid/data/csv/en"

text = requests.get(URL, timeout=60).text
with open(os.path.join(OUT, "snb_rendoblid_raw.csv"), "w") as f:
    f.write(text)

# the SNB file starts with a few info lines, then a header row "Date";"D0";"Value"
lines = text.splitlines()
start = next(i for i, line in enumerate(lines) if line.replace('"', "").startswith("Date"))
df = pd.read_csv(io.StringIO("\n".join(lines[start:])), sep=";")
print("maturities in the file:", sorted(df["D0"].unique()))

# "10J0" = 10-year Swiss Confederation yield (about 0.4% in 2025); "10J1" is a different, higher-yield 10-year series
ten = df[df["D0"].astype(str).str.upper().isin(["10J0", "10J", "10Y", "10"])].copy()
if ten.empty:
    raise SystemExit("No 10-year column found: send Claude the 'maturities in the file' line above")
ten["Value"] = pd.to_numeric(ten["Value"], errors="coerce")
ten = ten.dropna(subset=["Value"])[["Date", "Value"]].rename(columns={"Date": "observation_date", "Value": "CH10Y"})
ten.to_csv(os.path.join(OUT, "CH10Y.csv"), index=False)
print("CH10Y", len(ten), "rows from", ten.iloc[0, 0], "to", ten.iloc[-1, 0])
