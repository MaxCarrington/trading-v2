import pandas as pd

#Calculates the Average True Range (ATR) using Wilder's smoothing method.
#This is a fully optimized, vectorized implementation.
#
#ATR_t = (ATR_{t-1} * (n - 1) + TR_t) / n
#where:
#  TR_t = max(High - Low, abs(High - PrevClose), abs(Low - PrevClose))
#
# Intended for one-off / batch use (e.g. chart generation) where you want the
# whole ATR series at once. For a live bar-by-bar loop, use
# update_atr_incremental() below instead — recomputing this from bar 0 on
# every new bar makes the whole loop scale quadratically with history length.
def calculate_rolling_atr(series, lookback=14):
    # --- Calculate True Range (vectorized) ---
    high_low = series["High"] - series["Low"]
    high_prev_close = (series["High"] - series["Close"].shift(1)).abs()
    low_prev_close = (series["Low"] - series["Close"].shift(1)).abs()
    true_range = pd.concat([high_low, high_prev_close, low_prev_close], axis=1).max(axis=1)

    # --- Initialize ATR Series ---
    atr = pd.Series(index=series.index, dtype=float)

    # --- First ATR value: simple average of first N TR values ---
    atr.iloc[lookback - 1] = true_range.iloc[:lookback].mean()

    # --- Wilder’s recursive smoothing for all later values ---
    for i in range(lookback, len(series)):
        atr.iloc[i] = ((atr.iloc[i - 1] * (lookback - 1)) + true_range.iloc[i]) / lookback

    # Optional: forward fill first (lookback - 1) values for continuity
    atr.iloc[:lookback - 1] = atr.iloc[lookback - 1]

    return atr

# O(1)-per-bar incremental counterpart to calculate_rolling_atr(), for use in
# a live bar-by-bar backtest/trading loop. Produces the exact same values as
# calling calculate_rolling_atr() fresh on the full history after every bar
# (same seeding: a simple average of the first `lookback` true ranges, then
# Wilder's recursive smoothing) — it just carries the running state forward
# in `store` instead of replaying the whole history each time.
#
# Must be called on EVERY bar for a symbol, in order, starting from that
# symbol's first bar — skipping bars (e.g. only calling this once some later
# "warm-up" condition is met) would seed from the wrong window of true
# ranges and desync from what the batch function would have produced.
#
# `store` must already have "atr_value", "atr_prev_close", and
# "atr_tr_buffer" dicts keyed by symbol (see initialise_store()). Mutates
# and returns `store`; the running value is left in store["atr_value"][symbol]
# (None until there's enough history to seed it).
def update_atr_incremental(store, symbol, high, low, close, lookback=14):
    prev_close = store["atr_prev_close"].get(symbol)

    if prev_close is None:
        # First bar ever seen for this symbol — no previous close, so True
        # Range collapses to just High - Low (matches .shift(1) being NaN
        # and dropped by max(axis=1, skipna=True) in the batch version).
        true_range = high - low
    else:
        true_range = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close),
        )

    store["atr_prev_close"][symbol] = close

    current_atr = store["atr_value"].get(symbol)
    if current_atr is not None:
        # Already seeded — apply Wilder's recursive update.
        store["atr_value"][symbol] = ((current_atr * (lookback - 1)) + true_range) / lookback
        return store

    # Not yet seeded — accumulate true ranges until we have `lookback` of
    # them, then seed with their simple average (matches the batch
    # function's atr.iloc[lookback - 1] = true_range.iloc[:lookback].mean()).
    buffer = store["atr_tr_buffer"].setdefault(symbol, [])
    buffer.append(true_range)
    if len(buffer) >= lookback:
        store["atr_value"][symbol] = sum(buffer) / lookback
        store["atr_tr_buffer"][symbol] = []  # no longer needed once seeded

    return store
