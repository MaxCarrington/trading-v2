import pandas as pd
# Trigger if time in trade exceeds multiplier × half-life
def half_life_stop(multiplier, half_life, days_in_trade):
    return days_in_trade > half_life * multiplier

# Trigger if open‐order count exceeds allowed maximum
def inventory_stop(max_positions, positions):
    return len(positions) > max_positions

# Trigger trailing stop when latest close falls below
# highest high since entry × (1 − trail_percent)
def trailing_stop(highs, closes, entry_price, trail_percent):
    max_high = entry_price
    for h in highs:
        if h > max_high:
            max_high = h
    stop_price = max_high * (1 - trail_percent)
    return closes[-1] <= stop_price

# Trigger if loss on this trade > (5% of portfolio / number of trades)
def max_daily_loss_of_trade(current_price, entry_price, current_balance, positions, direction):
    max_port_loss = 0.05 * current_balance
    per_trade_loss = max_port_loss / max(1, len(positions))
    if direction > 0:
        loss = entry_price - current_price
    else:
        loss = current_price - entry_price
    return loss > per_trade_loss

# Calculate stop-loss price at half the take-profit distance
def fixed_stop_loss(trade_type, entry_price, multiplier=0.0125):
    if trade_type == 1:
        stop_loss = entry_price * (1 - multiplier)
    else:  # must be a sell
        stop_loss = entry_price * (1 + multiplier)
    return stop_loss

#    """
#    ATR-based stop loss. Distance from entry scales with recent volatility.
#
#    trade_type:   1 for Buy, anything else for Sell
#    entry_price:  trade entry price
#    atr_value:    current ATR (in price units, same scale as entry_price)
#    multiplier:   how many ATRs away to place the stop (typically 1.5 - 3.0)
def atr_stop_loss(trade_type, entry_price, atr_value, multiplier=2.0):

    if pd.isna(atr_value) or atr_value <= 0:
        raise ValueError(f"Invalid ATR for stop loss: {atr_value}")

    distance = atr_value * multiplier
    if trade_type == 1:
        return entry_price - distance
    else:
        return entry_price + distance


def compute_stop_loss(trade_type, entry_price, params, atr_value=None):
    """
    Dispatch to the right SL function based on params['stop_loss_type'].
    Returns the absolute stop-loss price.

    Config keys:
      stop_loss_type:  "pct" or "atr"
      stop_loss_value: multiplier (e.g. 0.01 for 1% pct, 2.0 for 2× ATR)
    """
    sl_type  = params.get("stop_loss_type", "pct")
    sl_value = params["stop_loss_value"]

    if sl_type == "pct":
        return fixed_stop_loss(trade_type, entry_price, multiplier=sl_value)
    elif sl_type == "atr":
        if atr_value is None:
            raise ValueError("ATR stop loss requires atr_value to be passed in")
        return atr_stop_loss(trade_type, entry_price, atr_value, multiplier=sl_value)
    else:
        raise ValueError(f"Unknown stop_loss_type: {sl_type!r}")