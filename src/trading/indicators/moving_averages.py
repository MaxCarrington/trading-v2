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