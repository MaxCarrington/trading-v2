# Taken from https://www.sciencedirect.com/science/article/pii/S0304405X24001399#fd15


# estimate_bid_ask_spread(...) computes the key moments from Section 3
# needed to estimate the bid–ask spread from OHLC data.
#
# • Uses a rolling window of bars up to a target index.
# • Defines the indicator τ_t:
#       τ_t = 0 if h_t = l_t = c_{t-1}  (flat / forward-filled bar)
#       τ_t = 1 otherwise
# • On τ_t = 1 bars, computes two log-returns:
#       x_t = log(mid_t) – log(open_t),   where mid_t = (high_t + low_t)/2
#       y_t = log(open_t) – log(close_{t-1})
# • De-means x_t and y_t, then computes their sample covariance Cov(x_t, y_t).
# • Also returns:
#       – the fraction of informative bars, P[τ_t = 1]
#       – the number of bars used
#
# These are the ingredients you plug into the paper’s Eq. (15)
# to obtain the bid–ask spread estimate.

#Returns a dict with:
# - cov_mid_open__open_prevclose: Cov[(η̄_t−o_t),(o_t−c_{t−1}) | τ_t=1]

# - p_tau_equals_1: fraction of bars with τ_t=1 in the window
# n_used: number of bars used in the covariance

def estimate_bid_ask_spread(ohlcv, time, *, window=252, debug=False):
    # ---- slice rolling window up to and including `time` ----
    if time not in ohlcv.index:
        raise ValueError(f"{time} not found in DataFrame index")
    end_loc = ohlcv.index.get_loc(time)
    if isinstance(end_loc, slice):  # duplicate index safeguard
        end_loc = end_loc.stop - 1
    start_loc = max(0, end_loc - window + 1)
    data = ohlcv.iloc[start_loc:end_loc + 1].copy()

    # ---- build arrays ----
    open_   = data["Open"].to_numpy()
    high    = data["High"].to_numpy()
    low     = data["Low"].to_numpy()
    close1  = data["Close"].shift(1).to_numpy()   # previous close

    # log terms (note: mid is avg in price space, then log)
    log_open  = np.log(open_)
    log_close = np.log(close1)
    log_mid   = np.log(0.5 * (high + low))

    # ---- indicator τ_t: 0 if high == low == prev close (with tolerance) ----
    tol = 1e-12
    has_prev      = np.isfinite(close1)
    high_eq_prev  = np.isclose(high,  close1, rtol=0.0, atol=tol)
    low_eq_prev   = np.isclose(low,   close1, rtol=0.0, atol=tol)
    is_flat       = has_prev & high_eq_prev & low_eq_prev
    tau           = ~is_flat                      # boolean mask on window
    frac_tau      = float(tau.mean()) if tau.size else 0.0  # P(τ=1)

    # ---- returns (as in Section 3): x = η̄ - o ; y = o - c_{t-1} ----
    x = log_mid  - log_open
    y = log_open - log_close

    # keep τ=1 and finite
    x = x[tau]; y = y[tau]
    fin = np.isfinite(x) & np.isfinite(y)
    x = x[fin]; y = y[fin]
    n_used = int(x.size)
    if n_used < 2 or frac_tau == 0.0:
        return 0.0

    # ---- conditional covariance on τ=1, then map to unconditional via P(τ=1) ----
    x -= x.mean()
    y -= y.mean()
    cov_cond = float(np.mean(x * y))         # Cov[ ... | τ=1 ]
    numer    = cov_cond * frac_tau           # E[ ... ] = Cov|τ=1 * P(τ=1)  (per Eq. 10→15)

    # ---- Eq. (15) denominator: joint probs P[o≠h, τ=1] + P[o≠l, τ=1] ----
    neq_open_high = ~np.isclose(open_, high, rtol=0.0, atol=tol)
    neq_open_low  = ~np.isclose(open_, low,  rtol=0.0, atol=tol)
    # conditional on τ=1
    cond_oh = float(np.mean(neq_open_high[tau])) if tau.any() else 0.0
    cond_ol = float(np.mean(neq_open_low[tau]))  if tau.any() else 0.0
    # joint = P(τ=1) * conditional
    p_oh_joint = frac_tau * cond_oh
    p_ol_joint = frac_tau * cond_ol
    denom = p_oh_joint + p_ol_joint
    if denom <= 0.0:
        return 0.0

    # ---- Eq. (15): S_o^2 = (-8 * E[(η̄ - o)(o - c_{t-1})]) / (P[o≠h,τ=1] + P[o≠l,τ=1]) ----
    s2 = (-8.0 * numer) / denom
    spread = float(np.sqrt(max(s2, 0.0)))   # relative spread (dimensionless)

    if debug:
        print("n_bars:", n_used)
        print("frac_tau:", frac_tau)
        print("P[o≠h | τ=1]:", cond_oh, "P[o≠l | τ=1]:", cond_ol)
        print("P[o≠h, τ=1]:", p_oh_joint, "P[o≠l, τ=1]:", p_ol_joint, "denom:", denom)
        print("cov_cond:", cov_cond, "numer:", numer, "spread:", spread)

    return spread


import numpy as np
import pandas as pd


def edge_effective_spread(df):
    """
    Estimate the effective bid-ask spread per day using the Efficient Discrete Generalized Estimator (EDGE).

    This implements the methodology of Ardia, Guidotti, & Kroencke (2024):contentReference[oaicite:10]{index=10} for daily OHLCV data.
    It returns the root mean square effective spread for each day (e.g. 0.01 = 1% spread), suitable for use in backtesting.

    Parameters:
        df (pd.DataFrame): DataFrame with columns 'open', 'high', 'low', 'close', 'volume' (volume is included for completeness
                           but not directly used in calculations). Prices should be sorted by date.

    Returns:
        pd.Series: A series containing the estimated spread for each day (as a decimal fraction).
                   The index matches the input DataFrame.

    Method:
        1. Identify no-trade days with indicator τ_t (τ_t = 0 if high==low==prev_close, else 1):contentReference[oaicite:11]{index=11}.
        2. Compute log-prices and the mid-price η_t = (log_high + log_low)/2.
        3. Calculate de-meaned returns:
           - r1_t = η_t − O_t (open-to-mid return on day t),
           - r2_t = O_t − η_{t-1} (return from previous mid to today’s open),
           - r3_t = η_t − C_{t-1} (mid price relative to yesterday’s close),
           - r4_t = C_{t-1} − η_{t-1} (previous close relative to previous mid),
           - r5_t = O_t − C_{t-1} (overnight return).
        4. Form two moment conditions using these returns (corresponding to different OHLC combinations):
           - First moment x1 involves Cov(η_t − O_t, O_t − C_{t-1}) = E[(r1_t)·(r5_t)]:contentReference[oaicite:13]{index=13}.
           - Second moment x2 involves Cov(C_t − η_t, …) similarly (using the complementary intraday movement).
           These expectations are computed over an expanding window up to each day.
        5. Compute probabilities needed for bias correction: P(O_t ≠ H_t | τ_t=1) and P(O_t ≠ L_t | τ_t=1), etc. This yields coefficients π_o and π_c as in the paper.
        6. Calculate preliminary spread-squared estimates from each moment: S^2_1 and S^2_2 (unbiased by construction).
        7. Calculate variances of each moment estimator over the window. Compute optimal weights w1, w2 ∝ 1/Var(S^2_1), 1/Var(S^2_2):contentReference[oaicite:14]{index=14} and combine the two estimates:
           S^2_EDGE = w1 * S^2_1 + w2 * S^2_2:contentReference[oaicite:15]{index=15}.
        8. Ensure non-negativity by setting S^2_EDGE = max(S^2_EDGE, 0). Then take S_EDGE = sqrt(S^2_EDGE).

    The function returns a Series of S_EDGE values for each day. A value of 0.01 indicates an estimated 1% bid-ask spread.
    """
    # Extract price series and convert to numpy arrays for speed
    open_price = df['Open'].to_numpy(dtype=float)
    high_price = df['High'].to_numpy(dtype=float)
    low_price = df['Low'].to_numpy(dtype=float)
    close_price = df['Close'].to_numpy(dtype=float)
    n = len(df)

    # Prepare output Series
    spread_series = pd.Series(index=df.index, dtype=float)

    if n < 3:
        # Not enough data to estimate (needs at least 3 days)
        return spread_series  # will be all NaN

    # Compute log-prices and mid-prices
    log_o = np.log(open_price)
    log_h = np.log(high_price)
    log_l = np.log(low_price)
    log_c = np.log(close_price)
    log_mid = (log_h + log_l) / 2.0  # η_t in log terms

    # Initialize arrays for intermediate calculations (index 0 will remain NaN due to lack of prev day)
    tau = np.full(n,
                  np.nan)  # trade indicator: 1 if any new price movement, 0 if forward-filled:contentReference[oaicite:18]{index=18}
    r1 = np.full(n, np.nan)
    r2 = np.full(n, np.nan)
    r3 = np.full(n, np.nan)
    r4 = np.full(n, np.nan)
    r5 = np.full(n, np.nan)

    tau[0] = np.nan
    for t in range(1, n):
        # Define tau_t: 0 if h_t = l_t = c_{t-1}, else 1:contentReference[oaicite:19]{index=19}
        if (high_price[t] == low_price[t] == close_price[t - 1]):
            tau[t] = 0.0
        else:
            tau[t] = 1.0
        # Compute de-meaned log-returns for moment conditions
        r1[t] = log_mid[t] - log_o[t]  # η_t - O_t (open-to-mid intraday return)
        r2[t] = log_o[t] - log_mid[t - 1]  # O_t - η_{t-1} (return from prev mid to current open)
        r3[t] = log_mid[t] - log_c[t - 1]  # η_t - C_{t-1}
        r4[t] = log_c[t - 1] - log_mid[t - 1]  # C_{t-1} - η_{t-1}
        r5[t] = log_o[t] - log_c[t - 1]  # O_t - C_{t-1} (overnight return)

    # Convert NaNs to 0 for safe cumulative sums (we will handle invalid windows separately)
    tau[np.isnan(tau)] = 0.0
    # Indicators for events (only count if tau_t = 1)
    ind_o_ne_high = ((open_price != high_price) & (tau == 1.0)).astype(float)  # 1 if open != high (on trading days)
    ind_o_ne_low = ((open_price != low_price) & (tau == 1.0)).astype(float)  # 1 if open != low  (on trading days)
    ind_c_ne_high = np.zeros(n, dtype=float)
    ind_c_ne_low = np.zeros(n, dtype=float)
    for t in range(1, n):
        # Previous day comparisons, only count on day t if day t has trading
        if tau[t] == 1.0:
            ind_c_ne_high[t] = 1.0 if close_price[t - 1] != high_price[t - 1] else 0.0
            ind_c_ne_low[t] = 1.0 if close_price[t - 1] != low_price[t - 1] else 0.0

    # Replace NaNs in returns with 0 for summation (r1...r5 for t=0 are NaN)
    r1[np.isnan(r1)] = 0.0
    r2[np.isnan(r2)] = 0.0
    r3[np.isnan(r3)] = 0.0
    r4[np.isnan(r4)] = 0.0
    r5[np.isnan(r5)] = 0.0

    # Compute cross-products needed for the two moment conditions and their variances
    r12 = r1 * r2  # corresponds to (η_t - O_t)*(O_t - η_{t-1})
    r15 = r1 * r5  # (η_t - O_t)*(O_t - C_{t-1}) used in first moment condition:contentReference[oaicite:20]{index=20}
    r34 = r3 * r4  # (η_t - C_{t-1})*(C_{t-1} - η_{t-1})
    r45 = r4 * r5  # (C_{t-1} - η_{t-1})*(O_t - C_{t-1})
    # Tau-weighted versions for conditional expectations
    tr2 = tau * r2
    tr4 = tau * r4
    tr5 = tau * r5
    tr1 = tau * r1

    # Pre-compute cumulative sums for needed terms (for expanding windows up to each day)
    cum_tau = np.cumsum(tau)
    cum_po = np.cumsum(ind_o_ne_high + ind_o_ne_low)  # sum of P(O != H) + P(O != L) events
    cum_pc = np.cumsum(ind_c_ne_high + ind_c_ne_low)  # sum of P(prev C != prev H) + P(prev C != prev L)
    cum_r1 = np.cumsum(r1)
    cum_r3 = np.cumsum(r3)
    cum_r4 = np.cumsum(r4)
    cum_r5 = np.cumsum(r5)
    cum_r12 = np.cumsum(r12)
    cum_r15 = np.cumsum(r15)
    cum_r34 = np.cumsum(r34)
    cum_r45 = np.cumsum(r45)
    cum_tr2 = np.cumsum(tr2)
    cum_tr4 = np.cumsum(tr4)
    cum_tr5 = np.cumsum(tr5)
    cum_tr2r12 = np.cumsum(tr2 * r12)
    cum_tr2r2 = np.cumsum(tr2 * r2)
    cum_tr4r34 = np.cumsum(tr4 * r34)
    cum_tr4r4 = np.cumsum(tr4 * r4)
    cum_r12r34 = np.cumsum(r12 * r34)
    cum_tr2r34 = np.cumsum(tr2 * r34)
    cum_tr4r12 = np.cumsum(tr4 * r12)
    cum_tr2r4 = np.cumsum(tr2 * r4)
    cum_tr5r15 = np.cumsum(tr5 * r15)
    cum_tr5r5 = np.cumsum(tr5 * r5)
    cum_tr4r45 = np.cumsum(tr4 * r45)
    cum_r15r45 = np.cumsum(r15 * r45)
    cum_tr5r45 = np.cumsum(tr5 * r45)
    cum_tr1r45 = np.cumsum(tr1 * r45)
    cum_tr4r5 = np.cumsum(tr4 * r5)

    # Loop through days to compute spread estimate for each day using data up to that day
    for i in range(n):
        if i < 2:
            spread_series.iat[i] = np.nan  # Need at least 3 data points for estimation
            continue
        count = i  # number of observations (t values) up to day i, since we start from t=1
        # Ensure there are enough trading days in sample and denominators non-zero
        if cum_tau[i] < 2 or cum_po[i] == 0 or cum_pc[i] == 0:
            spread_series.iat[i] = np.nan
            continue
        # Probabilities and coefficients π_o, π_c
        P_tau = cum_tau[i] / count
        P_o = cum_po[i] / count  # P(O != H or O != L) in sample (combined)
        P_c = cum_pc[i] / count  # P(prev C != prev H or prev L)
        π_o = -4.0 / P_o  # coefficient for open-based moment
        π_c = -4.0 / P_c  # coefficient for close-based moment
        # Conditional means on trading days (tau=1)
        E_r1_tau = cum_r1[i] / cum_tau[i]  # E[r1 | tau=1] = a3
        E_r4_tau = cum_r4[i] / cum_tau[i]  # E[r4 | tau=1] = a4
        E_r3_tau = cum_r3[i] / cum_tau[i]  # E[r3 | tau=1] = a5
        E_r5_tau = cum_r5[i] / cum_tau[i]  # E[r5 | tau=1] = a6
        # Moment condition expectations (unconditional means up to day i)
        E_r12 = cum_r12[i] / count
        E_tr2 = cum_tr2[i] / count
        E_r34 = cum_r34[i] / count
        E_r3 = cum_r3[i] / count
        E_r15 = cum_r15[i] / count
        E_tr5 = cum_tr5[i] / count
        E_r45 = cum_r45[i] / count
        E_r5 = cum_r5[i] / count
        # Compute the two unbiased spread-squared estimators (moment equations)
        # e1 corresponds to OHLC-type estimator, e2 to CHLO-type estimator
        S2_1 = π_o * (E_r12 - E_r1_tau * E_tr2) + π_c * (E_r34 - E_r4_tau * E_r3)
        S2_2 = π_o * (E_r15 - E_r1_tau * E_tr5) + π_c * (E_r45 - E_r4_tau * E_r5)
        # Compute variances of each moment estimator over the window (for weighting)
        # First, needed second moments and cross-moments (unconditional)
        E_r12_sq = np.sum(r12[:i + 1] ** 2) / count
        E_r34_sq = np.sum(r34[:i + 1] ** 2) / count
        E_r15_sq = np.sum(r15[:i + 1] ** 2) / count
        E_r45_sq = np.sum(r45[:i + 1] ** 2) / count
        E_tr2r12 = cum_tr2r12[i] / count
        E_tr2r2 = cum_tr2r2[i] / count
        E_tr4r34 = cum_tr4r34[i] / count
        E_tr4r4 = cum_tr4r4[i] / count
        E_r12r34 = cum_r12r34[i] / count
        E_tr2r34 = cum_tr2r34[i] / count
        E_tr4r12 = cum_tr4r12[i] / count
        E_tr2r4 = cum_tr2r4[i] / count
        E_tr5r15 = cum_tr5r15[i] / count
        E_tr5r5 = cum_tr5r5[i] / count
        E_tr4r45 = cum_tr4r45[i] / count
        E_r15r45 = cum_r15r45[i] / count
        E_tr5r45 = cum_tr5r45[i] / count
        E_tr1r45 = cum_tr1r45[i] / count
        E_tr4r5 = cum_tr4r5[i] / count
        # Variance formulas for each moment estimator (v1 for S2_1, v2 for S2_2)
        v1 = - S2_1 ** 2 + (
                π_o ** 2 * (E_r12_sq - 2 * E_r1_tau * E_tr2r12 + (E_r1_tau ** 2) * E_tr2r2) +
                π_c ** 2 * (E_r34_sq - 2 * E_r3_tau * E_tr4r34 + (E_r3_tau ** 2) * E_tr4r4) +
                2 * π_o * π_c * (E_r12r34 - E_r1_tau * E_tr2r34 - E_r3_tau * E_tr4r12 + E_r1_tau * E_r3_tau * E_tr2r4)
        )
        v2 = - S2_2 ** 2 + (
                π_o ** 2 * (E_r15_sq - 2 * E_r1_tau * E_tr5r15 + (E_r1_tau ** 2) * E_tr5r5) +
                π_c ** 2 * (E_r45_sq - 2 * E_r5_tau * E_tr4r45 + (E_r5_tau ** 2) * E_tr4r4) +
                2 * π_o * π_c * (E_r15r45 - E_r1_tau * E_tr5r45 - E_r5_tau * E_tr1r45 + E_r1_tau * E_r5_tau * E_tr4r5)
        )
        # Combine the two estimates with inverse-variance weighting:contentReference[oaicite:21]{index=21}
        total_var = v1 + v2
        if total_var > 0:
            S2_edge = (v2 * S2_1 + v1 * S2_2) / total_var
        else:
            S2_edge = 0.5 * (S2_1 + S2_2)  # fallback to simple average if variances are zero or undefined
        # Ensure non-negative spread
        if S2_edge < 0:
            S2_edge = 0.0
        spread_series.iat[i] = np.sqrt(S2_edge)  # effective spread (as a fraction of price)

    return spread_series

# Gets the value of a spread estimator in pips, needs passing a spread to be able to calcualte this
def get_value_in_pips(spread_est):
    value_in_pips = []
    for value in spread_est:
        value_in_pips.append(10000 * value)

    return value_in_pips