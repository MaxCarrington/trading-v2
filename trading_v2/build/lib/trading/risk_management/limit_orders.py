# Calculates a limit order price based on trade direction and entry price, adjusting by a percentage.
def calculate_limit_price(direction, entry_price, percentage=0.005):
    
    # Calculates limit price using direction: -1 for buy (price below market), +1 for sell (price above)
    if direction not in (-1, 1):
        raise ValueError("Direction must be -1 (buy) or +1 (sell).")

    return entry_price * (1 + direction * percentage)
