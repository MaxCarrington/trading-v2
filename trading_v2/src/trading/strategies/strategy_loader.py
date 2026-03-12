from src.trading.strategies.momentum_v1_2 import momentum_strategy_v1_2


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
def get_params(config: dict):
    strategy_name = config.get("strategy")
    pairs = config.get("symbols", [])
    timeframe = config.get("timeframe")
    start_date = config.get("start_date")
    end_date = config.get("end_date")
    year = config.get("year")

    if isinstance(pairs, str):
        pairs = [pairs]

    if strategy_name == 'momentum_v1.2':
        return {
            "strategy_name": strategy_name,
            "pairs": pairs,
            "timeframe": timeframe,
            "start_date": start_date,
            "end_date": end_date,
            "year": year,
            # pull parameters directly from config if present, else defaults
            "date": start_date,
            "momentum_lookback": config.get("parameters", {}).get("momentum_lookback", 12),
            "lookback": config.get("parameters", {}).get("lookback", {pair: 12 for pair in pairs}),
            "rsi_lookback": config.get("parameters", {}).get("rsi_lookback", {pair: 12 for pair in pairs}),
            "ma_lookback": config.get("parameters", {}).get("ma_lookback", {pair: 9 for pair in pairs}),
            "ma_thresh": config.get("parameters", {}).get("ma_thresh", {pair: 0.66 for pair in pairs}),
            "overbought_thresh": config.get("parameters", {}).get("overbought_thresh", {pair: 76 for pair in pairs}),
            "oversold_thresh": config.get("parameters", {}).get("oversold_thresh", {pair: 27 for pair in pairs}),
            "momentum_len_thresh": config.get("parameters", {}).get("momentum_len_thresh", {pair: 0.77 for pair in pairs}),
            "momentum_score_thresh": config.get("parameters", {}).get("momentum_score_thresh", {pair: 65 for pair in pairs}),
            "ma_type": config.get("parameters", {}).get("ma_type", "EMA"),
            "momentum_wSize": config.get("parameters", {}).get("momentum_wSize", {pair: 15 for pair in pairs}),
            "p_val_len_thresh": config.get("parameters", {}).get("p_val_len_thresh", {pair: 0.97 for pair in pairs}),
            # risk management
            "stop_loss_type": config.get("parameters", {}).get("stop_loss_type", "pct"),
            "stop_loss_value": config.get("parameters", {}).get("stop_loss_value", 0.01),
            "take_profit_type": config.get("parameters", {}).get("take_profit_type", "pct"),
            "take_profit_value": config.get("parameters", {}).get("take_profit_value", 0.02),
            "max_open_positions": config.get("parameters", {}).get("max_open_positions", 3),
            "position_size_type": config.get("parameters", {}).get("position_size_type", "fixed"),
            "position_size": config.get("parameters", {}).get("position_size", 1000),
        }
    else:
        raise ValueError(f'Unsupported strategy: {strategy_name}')
