# Walk-forward test for portfolio strategies (several pairs traded together, e.g. fx_momentum_v1.0).
#
# Same idea as walk_forward.py, but judged on the account's MONTHLY RETURNS instead of per-trade pips,
# because a portfolio's legs are traded together (their trades are not independent) and the equity curve
# is the only place where spread, resizing costs and overnight swap all show up.
#
# 1. Every grid setting is backtested once over the whole period (a strategy only looks at past bars).
# 2. For each test year, the setting with the best Sharpe of monthly returns over the train years is chosen.
# 3. The chosen setting's monthly returns in the test year are the out-of-sample result. All test years joined
#    together are checked against the pass rules.
#
# walk_forward "separate_pairs: true": each pair is backtested in its own account and the monthly returns are
# averaged (an equal-weighted portfolio). Used for index CFDs, which are each in their own currency.
#
# Run with: python scripts/walk_forward_portfolio.py --config strategies/fx_momentum_v1.0.yaml
import sys, os, json, itertools, importlib.util, logging
import pandas as pd
import numpy as np
from trading.utils.config import load_config
from trading.utils.paths import create_run_dir
from trading.utils.logger import start_log, info
from trading.strategies.strategy_loader import get_strategy, get_params
from trading.backtesting.risk_metrics import account_metrics

# Reuse the backtest loop and data loader from run_backtest.py (same folder as this script)
spec = importlib.util.spec_from_file_location("run_backtest", os.path.join(os.path.dirname(os.path.abspath(__file__)), "run_backtest.py"))
rb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rb)

config_path = sys.argv[2] if len(sys.argv) > 2 and sys.argv[1] == "--config" else "strategies/fx_momentum_v1.0.yaml"

def run_setting(config, setting):
    # One grid setting. Returns its monthly returns (net of every cost) and trades.
    if config["walk_forward"].get("separate_pairs"):
        parts = [run_one(config, setting, [pair]) for pair in (config.get("symbols") or config.get("pairs"))]
        returns = pd.concat([r for r, _ in parts], axis=1).fillna(0).mean(axis=1)
        return returns, pd.concat([t for _, t in parts], ignore_index=True)
    return run_one(config, setting, None)

def run_one(config, setting, pairs):
    logging.getLogger("trading").setLevel(logging.WARNING)
    params = get_params(config)
    params.update(setting)
    if pairs is not None:
        params["pairs"] = pairs
    data_list = rb._align_dataframes([rb._load_series_for_pair(pair, params) for pair in params["pairs"]])
    results = rb.backtest_live(data_list, get_strategy(config["strategy"]), params, 0.2, params["strategy_name"])
    net_worth = results["netWorthList"][:-1]                       # value after each bar (last = final close-out)
    equity = pd.Series(net_worth, index=data_list[0].index[2:2 + len(net_worth)])
    equity.index = equity.index + pd.Timedelta(hours=2)            # daily bars start 22:00 UTC the evening before
    monthly = equity.resample("ME").last()
    monthly = pd.concat([pd.Series([params["starting_capital"]], index=[monthly.index[0] - pd.offsets.MonthEnd(1)]), monthly])
    return monthly.pct_change().dropna(), results["trades_df"]

def sharpe(returns):
    if len(returns) < 2 or returns.std() == 0:
        return float("nan")
    return returns.mean() / returns.std() * 12 ** 0.5

def check_pass_rules(oos):
    t_stat = oos.mean() / oos.std() * len(oos) ** 0.5
    years = (1 + oos).groupby(oos.index.year).prod() - 1
    best = years.idxmax()
    without_best = oos[oos.index.year != best]
    return {
        "mean monthly return > 0":        (f"{oos.mean():.2%}", bool(oos.mean() > 0)),
        "t-stat > 2":                     (round(t_stat, 2), bool(t_stat > 2)),
        "at least 60% of years positive": (f"{(years > 0).mean():.0%}", bool((years > 0).mean() >= 0.6)),
        f"positive without best year ({best})": (f"{without_best.mean():.2%}", bool(without_best.mean() > 0)),
    }

if __name__ == "__main__":
    config = load_config(config_path)
    wf = config["walk_forward"]
    run_dir = create_run_dir(config["strategy"] + "_walk_forward")
    start_log(log_dir=run_dir, filename="run.log")

    # 1. Backtest every grid setting once over the whole period
    keys = list(wf["grid"])
    settings = [dict(zip(keys, values)) for values in itertools.product(*wf["grid"].values())]
    returns, grid_rows = {}, []
    for k, setting in enumerate(settings):
        name = " ".join(f"{key}={value}" for key, value in setting.items())
        returns[name], _ = run_setting(config, setting)
        info(f"[{k + 1}/{len(settings)}] {name}: Sharpe {sharpe(returns[name]):.2f}")
        for year, r in returns[name].groupby(returns[name].index.year):
            grid_rows.append({"setting": name, "year": year, "return": (1 + r).prod() - 1, "sharpe": sharpe(r)})
    pd.DataFrame(grid_rows).to_csv(os.path.join(run_dir, "grid_results.csv"), index=False)

    # 2. Each test year: choose on the train years, then trade the test year
    chosen, oos_parts = [], []
    for test_year in range(wf["first_test_year"], wf["last_test_year"] + 1):
        train = range(test_year - wf["train_years"], test_year)
        train_sharpe = {name: sharpe(r[r.index.year.isin(train)]) for name, r in returns.items()}
        best = max(train_sharpe, key=lambda n: -np.inf if np.isnan(train_sharpe[n]) else train_sharpe[n])
        test = returns[best][returns[best].index.year == test_year]
        oos_parts.append(test)
        chosen.append({"test_year": test_year, "setting": best, "train_sharpe": round(train_sharpe[best], 2),
                       "test_return": round((1 + test).prod() - 1, 4), "test_sharpe": round(sharpe(test), 2)})
        info(f"{test_year}: chose {best} (train Sharpe {train_sharpe[best]:.2f}) -> test return {(1 + test).prod() - 1:.1%}")
    oos = pd.concat(oos_parts)
    pd.DataFrame(chosen).to_csv(os.path.join(run_dir, "chosen_settings.csv"), index=False)
    oos.rename("return").to_csv(os.path.join(run_dir, "oos_monthly_returns.csv"))

    # 3. Pass rules on the joined out-of-sample months
    rules = check_pass_rules(oos)
    growth = (1 + oos).prod()
    summary = {"months": len(oos), "total_return": f"{growth - 1:.1%}",
               "annual_return": f"{growth ** (12 / len(oos)) - 1:.1%}", "sharpe": round(sharpe(oos), 2),
               "max_drawdown": f"{((1 + oos).cumprod() / (1 + oos).cumprod().cummax() - 1).min():.1%}",
               "metrics (monthly returns)": {k: round(float(v), 2) for k, v in account_metrics(oos, 12).items()},
               "pass_rules": {k: {"value": v[0], "pass": v[1]} for k, v in rules.items()},
               "passed": all(v[1] for v in rules.values())}
    with open(os.path.join(run_dir, "pass_rules.json"), "w") as f:
        json.dump(summary, f, indent=2)
    info(json.dumps(summary, indent=2))
    info(f"Results saved to {run_dir}")
