from ta.trend import SMAIndicator, EMAIndicator, WMAIndicator

def calculate_sma(series, lookback):
    if len(series) < lookback:
        lookback = len(series)
    return SMAIndicator(series, window=lookback).sma_indicator()

def calculate_ema(series, lookback):
    if len(series) < lookback:
        lookback = len(series)
    return EMAIndicator(series, window=lookback).ema_indicator()

def calculate_wma(series, lookback):
    if len(series) < lookback:
        lookback = len(series)
    return WMAIndicator(series, window=lookback).wma()

def calculate_moving_average(ma_type, series, lookback):
    if ma_type == "SMA":
        return calculate_sma(series, lookback)
    elif ma_type == "EMA":
        return calculate_ema(series, lookback)
    elif ma_type == "WMA":
        return calculate_wma(series, lookback)
    else:
        raise ValueError("ma_type must be sma, ema or wma")