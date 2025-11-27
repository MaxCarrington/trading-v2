from src.trading.strategies.momentum_v1_2 import momentum_strategy_v1_2

def get_strategy(strategy_name):
    if strategy_name == 'momentum_v1.2':
        return momentum_strategy_v1_2
    else:
        raise ValueError('Invalid strategy name')

def get_params(strategy_name, pairs, timeframe, date, year):
    if strategy_name == 'momentum_v1.2':
        # Normalize: if a single string is passed, wrap it in a list
        if isinstance(pairs, str):
            pairs = [pairs]

        return {
            "strategy_name": strategy_name,
            "pairs": pairs,
            "timeframe": timeframe,
            "date": date,
            "year": year,
            "lookback": {pair: 12 for pair in pairs},
            "holding_period": {pair: 34 for pair in pairs},
            "rsi_lookback": {pair: 12 for pair in pairs},
            "ma_lookback": {pair: 27 for pair in pairs},
            "ma_thresh": {pair: 0.66 for pair in pairs},
            "overbought_thresh": {pair: 76 for pair in pairs},
            "oversold_thresh": {pair: 27 for pair in pairs},
            "ma_type": "WMA",
            "momentum_wSize": {pair: 15 for pair in pairs},
            "p-val_len_thresh": {pair: 0.97 for pair in pairs},
            "momentum_len_thresh": {pair: 0.77 for pair in pairs},
            "momentum_score_thresh": {pair: 65 for pair in pairs},
        }
