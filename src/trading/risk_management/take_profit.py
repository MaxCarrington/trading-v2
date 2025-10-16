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

# Adapts to current market volatility by scaling the target off the Average True Range
def take_profit_atr(direction, entry_price, atr_value, multiplier=2):
    offset = atr_value * multiplier
    return entry_price + offset if direction > 0 else entry_price - offset

# Calculate take-profit price for a given trade type and entry price
def calculate_take_profit(trade_type, entry_price):
    if trade_type == "buy":
        exit_price = entry_price * 1.25
    else:  # must be a sell
        exit_price = entry_price * 0.75
    return exit_price

