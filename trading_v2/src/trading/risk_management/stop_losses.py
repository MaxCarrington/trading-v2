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

