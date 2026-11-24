import math

# Tracks trade outcomes and computes a scaled & capped Kelly position size, with optional EMA smoothing of win rate and win/loss ratio.
class KellySizer:
    def __init__(self, alpha=0.1, kelly_cap=0.5, kelly_scale=1.0, use_ema=False):
        # smoothing factor for EMA; ignored if use_ema is False
        self.alpha = alpha
        # maximum fraction of capital to allocate
        self.kelly_cap = kelly_cap
        # scale factor (e.g. 0.5 to take half-Kelly)
        self.kelly_scale = kelly_scale
        # whether to smooth metrics via EMA
        self.use_ema = use_ema

        # empirical stats
        self.wins = 0
        self.losses = 0
        self.sum_gains = 0.0
        self.sum_losses = 0.0

        # EMA state
        self.ema_win_rate = None
        self.ema_gain = None
        self.ema_loss = None

    # Record one trade’s PnL and update empirical counts and optional EMA statistics.
    def record_trade(self, pnl):
        is_win = pnl > 0
        gain = pnl if is_win else 0.0
        loss = abs(pnl) if not is_win else 0.0

        # update empirical
        if is_win:
            self.wins += 1
            self.sum_gains += gain
        else:
            self.losses += 1
            self.sum_losses += loss

        # update EMA if desired
        if self.use_ema:
            if self.ema_win_rate is None:
                self.ema_win_rate = 1.0 if is_win else 0.0
                self.ema_gain = gain
                self.ema_loss = loss
            else:
                self.ema_win_rate = (
                    self.alpha * (1.0 if is_win else 0.0)
                    + (1 - self.alpha) * self.ema_win_rate
                )
                if is_win:
                    self.ema_gain = self.alpha * gain + (1 - self.alpha) * self.ema_gain
                else:
                    self.ema_loss = self.alpha * loss + (1 - self.alpha) * self.ema_loss

    # Return empirical or EMA-smoothed win probability [0,1].
    def get_win_probability(self):
        if self.use_ema:
            return self.ema_win_rate or 0.0
        total = self.wins + self.losses
        return (self.wins / total) if total > 0 else 0.0

    # Return empirical or EMA-smoothed win/loss ratio (avg gain / avg loss).
    # Infinite if no losses; zero if no wins.
    def get_win_loss_ratio(self):
        if self.use_ema:
            if (self.ema_loss or 0.0) == 0.0:
                return math.inf if (self.ema_gain or 0.0) > 0 else 0.0
            return (self.ema_gain or 0.0) / self.ema_loss

        if self.losses == 0:
            return math.inf if self.wins > 0 else 0.0
        avg_gain = (self.sum_gains / self.wins) if self.wins > 0 else 0.0
        avg_loss = (self.sum_losses / self.losses) if self.losses > 0 else 0.0
        return (avg_gain / avg_loss) if avg_loss > 0 else 0.0

    # Apply Kelly formula k = p - (1-p)/r, clamp to [0, kelly_cap], then apply kelly_scale.
    def calculate_kelly(self):
        p = self.get_win_probability()
        r = self.get_win_loss_ratio()

        if p <= 0 or r <= 0:
            return 0.0

        if math.isinf(r):
            k = self.kelly_cap
        else:
            k = p - (1 - p) / r
            k = max(0.0, min(k, self.kelly_cap))

        return round(k * self.kelly_scale, 4)

    # Return the next position size (fraction of capital).
    def next_size(self):
        return self.calculate_kelly()

# Factory function to get a new KellySizer instance
def initialise_kelly(alpha=0.1, kelly_cap=0.5, kelly_scale=1.0, use_ema=False):
    return KellySizer(alpha, kelly_cap, kelly_scale, use_ema)
