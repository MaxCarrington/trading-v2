# Walk-forward test: re-optimise every year on the previous years, then trade the next year with the winner.
#
# How it works:
# 1. Every grid setting is backtested once over the whole period (plus one warm-up year for the trend filter).
#    A strategy only looks at past bars, so a trade in 2012 is the same whether the run started in 2007 or 2011.
# 2. For each test year, the setting with the best Sharpe on the train years is chosen.
#    Only train-year trades are used to choose it.
# 3. The chosen setting's trades in the test year are the out-of-sample result. Joining every test year
#    gives one out-of-sample record, checked against the pass rules.
#
# Results are in pips (net of costs), so they don't depend on the account balance.
# Run with: python scripts/walk_forward.py --config strategies/london_breakout_v1.4_walk_forward.yaml
import sys, os, json, itertools, importlib.util, logging
from concurrent.futures import ProcessPoolExecutor
import pandas as pd
import trading.utils.constants as constants
from trading.utils.config import load_config
from trading.utils.paths import create_run_dir
from trading.utils.logger import start_log, info
from trading.strategies.strategy_loader import get_strategy, get_params
from trading.backtesting.metrics_report import generate_report
from trading.backtesting.trade_dashboard import compute_stats, build_dashboard

# Reuse the backtest loop and data loader from run_backtest.py (same folder as this script)
spec = importlib.util.spec_from_file_location("run_backtest", os.path.join(os.path.dirname(os.path.abspath(__file__)), "run_backtest.py"))
rb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rb)

config_path = sys.argv[2] if len(sys.argv) > 2 and sys.argv[1] == "--config" else "strategies/london_breakout_v1.4_walk_forward.yaml"
SHARPE = "Sharpe (annual, daily P&L)"

def get_window(config):
    wf = config["walk_forward"]
    first_year = wf["first_test_year"] - wf["train_years"] - 1    # one extra year to warm up the trend filter
    return first_year, wf["last_test_year"]

def run_setting(setting):
    # One full backtest for one grid setting. Returns its trades.
    logging.getLogger("trading").setLevel(logging.WARNING)       # hide the per-order log lines
    config = load_config(config_path)
    params = get_params(config)
    first_year, last_year = get_window(config)
    params["start_date"], params["end_date"] = str(first_year), str(last_year)
    params.update(setting)
    data_list = rb._align_dataframes([rb._load_series_for_pair(pair, params) for pair in params["pairs"]])
    results = rb.backtest_live(data_list, get_strategy(config["strategy"]), params, 0.2, params["strategy_name"])
    trades = results["trades_df"]
    trades["entry_date"] = pd.to_datetime(trades["entry_date"])
    trades["exit_date"] = pd.to_datetime(trades["exit_date"])
    return trades

def year_stats(trades):
    # Net pips per trade, Sharpe, profit factor and trade count for a set of trades
    if len(trades) < 2:
        return {"trades": len(trades), "net_per_trade": float("nan"), "sharpe": float("nan"), "profit_factor": float("nan")}
    s = compute_stats(trades.sort_values("exit_date").reset_index(drop=True))
    return {"trades": len(trades), "net_per_trade": trades["profit"].mean(), "sharpe": s[SHARPE], "profit_factor": s["Profit factor"]}

def check_pass_rules(oos, by_year):
    p = oos["profit"]
    t_stat = p.mean() / p.std() * len(p) ** 0.5
    year_totals = by_year["total_pips"]
    best_year = year_totals.idxmax()
    without_best = oos[oos["entry_date"].dt.year != best_year]["profit"].mean()
    rules = {
        "net pips per trade > 0":         (round(p.mean(), 2), bool(p.mean() > 0)),
        "t-stat > 2":                     (round(t_stat, 2), bool(t_stat > 2)),
        "at least 60% of years positive": (f"{(year_totals > 0).mean():.0%}", bool((year_totals > 0).mean() >= 0.6)),
        f"positive without best year ({best_year})": (round(without_best, 2), bool(without_best > 0)),
    }
    return rules

if __name__ == "__main__":
    config = load_config(config_path)
    wf = config["walk_forward"]
    strategy_name = config["strategy"] + "_walk_forward"
    run_dir = create_run_dir(strategy_name)
    start_log(log_dir=run_dir, filename="run.log")

    # 1. Backtest every grid setting once over the whole period
    names = list(wf["grid"].keys())
    settings = [dict(zip(names, values)) for values in itertools.product(*wf["grid"].values())]
    info(f"Running {len(settings)} grid settings over {get_window(config)[0]}-{wf['last_test_year']} with {wf['workers']} workers...")
    with ProcessPoolExecutor(max_workers=wf["workers"]) as pool:
        all_trades = list(pool.map(run_setting, settings))

    # 2. Each test year: pick the best setting on the train years, then keep its trades in the test year
    grid_rows, chosen_rows, oos_trades = [], [], []
    for test_year in range(wf["first_test_year"], wf["last_test_year"] + 1):
        train_years = list(range(test_year - wf["train_years"], test_year))
        best = None
        for i, (setting, trades) in enumerate(zip(settings, all_trades)):
            train = year_stats(trades[trades["entry_date"].dt.year.isin(train_years)])
            grid_rows.append({"test_year": test_year, **setting, **{f"train_{k}": v for k, v in train.items()}})
            if best is None or train["sharpe"] > best[1]["sharpe"]:
                best = (i, train)
        i, train = best
        test = all_trades[i][all_trades[i]["entry_date"].dt.year == test_year]
        oos_trades.append(test)
        chosen_rows.append({"test_year": test_year, "train_years": f"{train_years[0]}-{train_years[-1]}", **settings[i],
                            "train_sharpe": train["sharpe"], "train_net_per_trade": train["net_per_trade"],
                            **{f"test_{k}": v for k, v in year_stats(test).items()}, "total_pips": test["profit"].sum()})
        info(f"{test_year}: chose {settings[i]} (train Sharpe {train['sharpe']:.2f}) -> test {len(test)} trades, "
             f"{test['profit'].mean():+.2f} pips/trade")

    # 3. Join the test years into one out-of-sample record and check the pass rules
    oos = pd.concat(oos_trades, ignore_index=True)
    chosen = pd.DataFrame(chosen_rows).set_index("test_year")
    rules = check_pass_rules(oos, chosen)

    pd.DataFrame(grid_rows).to_csv(os.path.join(run_dir, "grid_results.csv"), index=False)
    chosen.to_csv(os.path.join(run_dir, "chosen_settings.csv"))
    oos.to_csv(os.path.join(run_dir, "trades.csv"), index=False)
    with open(os.path.join(run_dir, "pass_rules.json"), "w") as f:
        json.dump({rule: {"value": v, "passed": ok} for rule, (v, ok) in rules.items()}, f, indent=2, default=str)

    info("=" * 60)
    info("WALK-FORWARD (out of sample)")
    info("=" * 60)
    info("\n" + chosen.round(2).to_string())
    for rule, (value, ok) in rules.items():
        info(f"{'PASS' if ok else 'FAIL'}  {rule}: {value}")
    info(f"Overall: {'PASSED' if all(ok for _, ok in rules.values()) else 'FAILED'}")

    # Each pair on its own (useful when the config trades more than one pair)
    by_pair = oos.groupby("asset")["profit"].agg(trades="count", net_per_trade="mean", total_pips="sum")
    by_pair["t_stat"] = oos.groupby("asset")["profit"].apply(lambda p: p.mean() / p.std() * len(p) ** 0.5)
    by_pair["years_positive"] = oos.groupby(["asset", oos["entry_date"].dt.year])["profit"].sum().gt(0).groupby("asset").mean()
    by_pair.to_csv(os.path.join(run_dir, "by_pair.csv"))
    info("By pair:\n" + by_pair.round(2).to_string())

    # Reports for the joined out-of-sample trades (same files as a normal backtest run)
    generate_report(run_dir)
    params = get_params(config)
    params["start_date"], params["end_date"] = str(wf["first_test_year"]), str(wf["last_test_year"])
    data_list = rb._align_dataframes([rb._load_series_for_pair(pair, params) for pair in params["pairs"]])
    build_dashboard(run_dir, data_list, params)
    info(f"Full walk-forward output saved to: {run_dir}")
