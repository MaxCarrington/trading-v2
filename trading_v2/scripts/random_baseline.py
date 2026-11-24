# Random-entry baseline: does a strategy beat random entries with the same holding times?
#
# For each of n_runs random runs: take the strategy's trades, keep each trade's holding time (in bars),
# but move its entry to a random day on which the strategy was allowed to trade (here: close above the
# 200-day average, the trend filter). Enter at the next open, exit at the open after the same number of days,
# pay the same costs. If the strategy's average trade is not better than most random runs, the entry
# signal adds nothing: the result comes from the market drifting up, the holding time, or luck.
#
# Run with: python scripts/random_baseline.py --config strategies/index_dip_v1.0.yaml --trades results/.../trades.csv
import sys, os, argparse, importlib.util
import numpy as np
import pandas as pd
from trading.utils.config import load_config
from trading.strategies.strategy_loader import get_params

spec = importlib.util.spec_from_file_location("run_backtest", os.path.join(os.path.dirname(os.path.abspath(__file__)), "run_backtest.py"))

def random_baseline(price, trades, cost_pct, n_runs=1000, trend_days=200, seed=0):
    # price: daily OHLC (Open/Close), trades: the strategy's trades with "days" held and "profit" in % per trade
    rng = np.random.default_rng(seed)
    opens = price["Open"].to_numpy()
    allowed = np.where(price["Close"] > price["Close"].rolling(trend_days).mean())[0]
    allowed = allowed[allowed < len(price) - 12]          # leave room for the longest hold
    holds = trades["days"].to_numpy()
    averages = []
    for _ in range(n_runs):
        signal_days = rng.choice(allowed, size=len(holds))
        entry = opens[signal_days + 1]
        exit_ = opens[signal_days + 1 + holds]
        averages.append(np.mean(100 * (exit_ / entry - 1) - cost_pct))
    averages = np.array(averages)
    strategy = trades["profit"].mean()
    return {"strategy % per trade": round(strategy, 3), "random % per trade (average)": round(averages.mean(), 3),
            "random 95th percentile": round(np.percentile(averages, 95), 3),
            "beats % of random runs": round(100 * (averages < strategy).mean(), 1)}

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--config"); ap.add_argument("--trades"); ap.add_argument("--runs", type=int, default=1000)
    a = ap.parse_args()
    sys.argv = ["run_backtest.py", "--config", a.config]       # run_backtest.py reads its config at import
    rb = importlib.util.module_from_spec(spec); spec.loader.exec_module(rb)
    params = get_params(load_config(a.config))
    trades = pd.read_csv(a.trades)
    for pair in params["pairs"]:
        price = rb._load_series_for_pair(pair, params)
        t = trades[trades["asset"] == pair]
        print(pair, random_baseline(price, t, 2 * params["costs"]["commission_pct"], a.runs))
