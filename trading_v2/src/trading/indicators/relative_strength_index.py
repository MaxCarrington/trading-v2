from ta.momentum import RSIIndicator

# --- RSI checks ---
def is_rsi_oversold(rsi, oversold_thresh):
    return rsi < oversold_thresh

def is_rsi_overbought(rsi, overbought_thresh):
    return rsi > overbought_thresh

# --- Indicator calculators ---
def calculate_rsi(series, lookback):
    if lookback <= 0:
        raise ValueError("Error: Lookback must be positive")
    if lookback >= len(series):
        lookback = len(series) - 1
    return RSIIndicator(series, window=lookback).rsi()