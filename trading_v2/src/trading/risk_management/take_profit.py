import pandas as pd
# Fixed risk-reward: TP = entry + (entry - stop_loss) × reward_ratio for longs (inverse for shorts)
def take_profit_risk_reward(direction, entry_price, stop_loss_price, reward_ratio=2.0):
    risk = abs(entry_price - stop_loss_price)
    if direction > 0:  # long
        return entry_price + risk * reward_ratio
    else:              # short
        return entry_price - risk * reward_ratio

# Ties the take-profit directly to the stop-loss, so every trade has a known reward/risk ratio.
def take_profit_risk_reward_stop_loss(direction, entry_price, stop_loss_price, reward_ratio=2.0):
    risk = abs(entry_price - stop_loss_price)
    return entry_price + risk * reward_ratio if direction > 0 else entry_price - risk * reward_ratio

#    """
#    ATR-based stop loss. Distance from entry scales with recent volatility.
#
#    trade_type:   1 for Buy, anything else for Sell
#    entry_price:  trade entry price
#    atr_value:    current ATR (in price units, same scale as entry_price)
#    multiplier:   how many ATRs away to place the stop (typically 1.5 - 3.0)
def atr_take_profit(trade_type, entry_price, atr_value, multiplier=2.0):
    if pd.isna(atr_value) or atr_value <= 0:
        raise ValueError(f"Invalid ATR for take profit: {atr_value}")
    distance = atr_value * multiplier
    if trade_type == 1:
        return entry_price + distance
    else:
        return entry_price - distance

# Calculate take-profit price for a given trade type and entry price
def fixed_take_profit(trade_type, entry_price, multiplier=0.025):
    if trade_type == 1:
        exit_price = entry_price * (1 + multiplier)
    else:  # must be a sell
        exit_price = entry_price * (1 - multiplier)
    return exit_price

def compute_take_profit(trade_type, entry_price, params, atr_value=None):
    """
    Dispatch to the right TP function based on params['take_profit_type'].
    Returns the absolute take-profit price.

    Config keys:
      take_profit_type:  "pct" or "atr"
      take_profit_value: multiplier (e.g. 0.025 for 2.5% pct, 3.0 for 3× ATR)
    """
    tp_type = params.get("take_profit_type", "pct")
    tp_value = params["take_profit_value"]

    if tp_type == "pct":
        return fixed_take_profit(trade_type, entry_price, multiplier=tp_value)
    elif tp_type == "atr":
        if atr_value is None:
            raise ValueError("ATR take profit requires atr_value to be passed in")
        return atr_take_profit(trade_type, entry_price, atr_value, multiplier=tp_value)
    else:
        raise ValueError(f"Unknown take profit type: {tp_type!r}")