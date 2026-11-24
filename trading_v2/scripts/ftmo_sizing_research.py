# Research: how to size the month-end strategy to pass FTMO's 2-Step and keep the funded account (2005-2018 only).
#   PYTHONPATH=src python scripts/ftmo_sizing_research.py
# Grid: leverage x drawdown brake, each run with no buffer and with a 1% daily buffer (for intraday dips).
import os
import itertools
import pandas as pd
import trading.utils.constants as constants
from trading.utils.config import load_config
from trading.backtesting.prop_challenge import simulate, summary

cfg = load_config("analysis/prop_challenge.yaml")
eq = pd.read_csv(os.path.join(constants.ROOT_DIR, cfg["equity_file"]), index_col=0, parse_dates=True)
eq = eq[(eq.index.year >= cfg["start_year"]) & (eq.index.year <= cfg["end_year"])]
daily = (1 + eq / (cfg["starting_capital"] / eq.shape[1])).pct_change().fillna(0).mean(axis=1)

rows = []
for lev, brake, buffer in itertools.product(cfg["leverages"], [0, 3, 5], [0, 1]):
    rules = dict(cfg["rules"], **{"brake_at_%": brake, "daily_buffer_%": buffer})
    s = summary(simulate(daily, rules, lev), rules, lev)
    rows.append({"brake at %": brake, "daily buffer %": buffer, **s})
table = pd.DataFrame(rows)
out = os.path.join(constants.RESULTS_DIR, "prop_challenge")
os.makedirs(out, exist_ok=True)
table.to_csv(os.path.join(out, "ftmo_sizing_grid_2005_2018.csv"), index=False)
pd.set_option("display.width", 220)
print(table.drop(columns=["attempts"]).to_string(index=False))
