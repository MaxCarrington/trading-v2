from trading.strategies.london_breakout_v1_0 import london_breakout_v1_0
from trading.strategies.london_breakout_v1_1 import london_breakout_v1_1
from trading.strategies.london_breakout_v1_2 import london_breakout_v1_2
from trading.strategies.london_breakout_v1_3 import london_breakout_v1_3
from trading.strategies.london_breakout_v1_4 import london_breakout_v1_4
from trading.strategies.london_breakout_v1_5 import london_breakout_v1_5
from trading.strategies.london_breakout_v1_6 import london_breakout_v1_6
from trading.strategies.fx_momentum_v1_0 import fx_momentum_v1_0
from trading.strategies.index_mean_reversion_v1_0 import index_mean_reversion_v1_0
from trading.strategies.index_dip_v1_0 import index_dip_v1_0
from trading.strategies.momentum_v1_2 import momentum_strategy_v1_2
from trading.strategies.momentum_v1_3 import momentum_strategy_v1_3
from trading.utils.logger import start_log, info, warning, error

def get_strategy(strategy_name: str):
    info(strategy_name)
    if strategy_name == 'momentum_v1.2':
        return momentum_strategy_v1_2
    elif strategy_name == 'momentum_v1.3':
        return momentum_strategy_v1_3
    elif strategy_name == "london_breakout_v1.0":
        return london_breakout_v1_0
    elif strategy_name == "london_breakout_v1.1":
        return london_breakout_v1_1
    elif strategy_name == "london_breakout_v1.2":
        return london_breakout_v1_2
    elif strategy_name == "london_breakout_v1.3":
        return london_breakout_v1_3
    elif strategy_name == "london_breakout_v1.4":
        return london_breakout_v1_4
    elif strategy_name == "london_breakout_v1.5":
        return london_breakout_v1_5
    elif strategy_name == "london_breakout_v1.6":
        return london_breakout_v1_6
    elif strategy_name == "fx_momentum_v1.0":
        return fx_momentum_v1_0
    elif strategy_name == "index_mean_reversion_v1.0":
        return index_mean_reversion_v1_0
    elif strategy_name == "index_dip_v1.0":
        return index_dip_v1_0
    else:
        raise ValueError(f'Invalid strategy name: {strategy_name}')

def get_params(config):
    parameters = config.get("parameters")
    if parameters is None:
        raise KeyError("Config missing top-level 'parameters' key")

    pairs = config.get("symbols") or config.get("pairs", [])
    if not pairs:
        raise KeyError("Config missing 'symbols' (or 'pairs')")

    if config.get("strategy") == "momentum_v1.2":
        return read_params(config)
    elif config.get("strategy") == "momentum_v1.3":
        return read_params(config)
    elif config.get("strategy") == "mean_reversion_v1.0":
        return read_params(config)
    elif config.get("strategy") == "london_breakout_v1.0":
        return read_params(config)
    elif config.get("strategy") == "london_breakout_v1.1":
        return read_params(config)
    elif config.get("strategy") == "london_breakout_v1.2":
        return read_params(config)
    elif config.get("strategy") == "london_breakout_v1.3":
        return read_params(config)
    elif config.get("strategy") == "london_breakout_v1.4":
        return read_params(config)
    elif config.get("strategy") == "london_breakout_v1.5":
        return read_params(config)
    elif config.get("strategy") == "london_breakout_v1.6":
        return read_params(config)
    elif config.get("strategy") == "fx_momentum_v1.0":
        return read_params(config)
    elif config.get("strategy") == "index_mean_reversion_v1.0":
        return read_params(config)
    elif config.get("strategy") == "index_dip_v1.0":
        return read_params(config)
    else:
        raise ValueError(f"Invalid strategy name: {(config.get('strategy'))}")

def read_params(config):
    # Turns a strategy config into one flat params dict, so params["exit_hour"] works directly.
    # Top-level keys (symbols, timeframe, costs, ...) and everything under "parameters" end up at the same level.
    params = {k: v for k, v in config.items() if k != "parameters"}
    params.update(config.get("parameters") or {})

    # Names the backtester expects
    params["strategy_name"] = config["strategy"]
    params["pairs"] = config.get("symbols") or config.get("pairs")
    params["date"] = config.get("start_date")   # legacy alias, still used by the engine
    return params