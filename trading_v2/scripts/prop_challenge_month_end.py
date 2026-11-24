# Runs the month-end stocks-vs-bonds strategy through the prop-firm challenge rules.
#   PYTHONPATH=src python scripts/prop_challenge_month_end.py
# Settings: configs/analysis/prop_challenge.yaml (research dates only, 2005-2018).
import os
import pandas as pd
import trading.utils.constants as constants
from trading.utils.config import load_config
from trading.backtesting.prop_challenge import simulate, summary

cfg = load_config("analysis/prop_challenge.yaml")
rules = cfg["rules"]

# daily account returns: each market's column is its P&L on 1/n of the capital, so rebuild each market's growth
eq = pd.read_csv(os.path.join(constants.ROOT_DIR, cfg["equity_file"]), index_col=0, parse_dates=True)
eq = eq[(eq.index.year >= cfg["start_year"]) & (eq.index.year <= cfg["end_year"])]
share = cfg["starting_capital"] / eq.shape[1]
daily = (1 + eq / share).pct_change().fillna(0).mean(axis=1)
print(f"{daily.index[0].date()} to {daily.index[-1].date()}, in the market {100 * (daily != 0).mean():.0f}% of days")
print("rules:", rules)

table = []
for lev in cfg["leverages"]:
    attempts = simulate(daily, rules, lev)
    table.append(summary(attempts, rules, lev))
    out = os.path.join(constants.RESULTS_DIR, "prop_challenge")
    os.makedirs(out, exist_ok=True)
    attempts.to_csv(os.path.join(out, f"month_end_attempts_lev{lev}.csv"), index=False)
pd.set_option("display.width", 200)
print(pd.DataFrame(table).to_string(index=False))
