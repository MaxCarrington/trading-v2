from trading.strategies.momentum_v1_2 import momentum_strategy_v1_2


def get_strategy(strategy_name: str):
    print(strategy_name)
    if strategy_name == 'momentum_v1.2':
        return momentum_strategy_v1_2
    else:
        raise ValueError(f'Invalid strategy name: {strategy_name}')

#Accepts a config dict (from YAML) and returns a normalized params dict.
#    Expected keys in config:
#      - strategy
#      - symbols
#      - timeframe
#      - date
#      - year
#      - plus any indicator/risk/filter parameters
def get_params(config):
    parameters = config.get("parameters")
    if parameters is None:
        raise KeyError("Config missing top-level 'parameters' key")

    pairs = config.get("symbols") or config.get("pairs", [])
    if not pairs:
        raise KeyError("Config missing 'symbols' (or 'pairs')")

    required_top_level = [
        "strategy", "timeframe", "year",
        "start_date", "end_date",
        "provider", "security_type", "starting_capital",
    ]
    missing_top = [k for k in required_top_level if config.get(k) is None]
    if missing_top:
        raise KeyError(f"Config missing top-level keys: {missing_top}")

    required_keys = [
        "momentum_lookback", "lookback", "rsi_lookback", "ma_lookback",
        "ma_thresh", "overbought_thresh", "oversold_thresh",
        "momentum_len_thresh", "momentum_score_thresh", "ma_type",
        "momentum_wSize", "p_val_len_thresh", "max_holding_duration",
        "stop_loss_type", "stop_loss_value",
        "take_profit_type", "take_profit_value",
        "max_open_positions",
        "position_size_type", "position_size",
    ]
    missing = [k for k in required_keys if k not in parameters]
    if missing:
        raise KeyError(f"Config 'parameters' missing keys: {missing}")

    per_symbol_keys = [
        "lookback", "rsi_lookback", "ma_lookback", "ma_thresh",
        "overbought_thresh", "oversold_thresh",
        "momentum_len_thresh", "momentum_score_thresh",
        "momentum_wSize", "p_val_len_thresh",
    ]
    for key in per_symbol_keys:
        d = parameters[key]
        if not isinstance(d, dict):
            raise TypeError(f"Config 'parameters.{key}' must be a dict, got {type(d).__name__}")
        missing_pairs = [p for p in pairs if p not in d]
        if missing_pairs:
            raise KeyError(f"'parameters.{key}' missing entries for: {missing_pairs}")

    return {
        # top level
        "strategy_name":          config["strategy"],
        "provider":               config["provider"],
        "security_type":          config["security_type"],
        "starting_capital":       config["starting_capital"],
        "timeframe":              config["timeframe"],
        "start_date":             config["start_date"],
        "end_date":               config["end_date"],
        "year":                   config["year"],
        "date":                   config["start_date"],   # legacy alias
        "pairs":                  pairs,

        # strategy parameters
        "momentum_lookback":      parameters["momentum_lookback"],
        "lookback":               parameters["lookback"],
        "rsi_lookback":           parameters["rsi_lookback"],
        "ma_lookback":            parameters["ma_lookback"],
        "ma_thresh":              parameters["ma_thresh"],
        "overbought_thresh":      parameters["overbought_thresh"],
        "oversold_thresh":        parameters["oversold_thresh"],
        "momentum_len_thresh":    parameters["momentum_len_thresh"],
        "momentum_score_thresh":  parameters["momentum_score_thresh"],
        "ma_type":                parameters["ma_type"],
        "momentum_wSize":         parameters["momentum_wSize"],
        "p_val_len_thresh":       parameters["p_val_len_thresh"],
        "max_holding_duration":   parameters["max_holding_duration"],

        # risk management
        "stop_loss_type":     parameters["stop_loss_type"],
        "stop_loss_value":    parameters["stop_loss_value"],
        "take_profit_type":   parameters["take_profit_type"],
        "take_profit_value":  parameters["take_profit_value"],
        "max_open_positions": parameters["max_open_positions"],
        "position_size_type": parameters["position_size_type"],
        "position_size":      parameters["position_size"],
    }