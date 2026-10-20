# Account-level risk and return metrics from a series of period returns (daily or monthly).
#
# returns: pandas Series of simple returns per period (0.01 = +1%), in time order
# periods_per_year: 252 for daily returns, 12 for monthly
# win_rate: % of winning trades, if known (otherwise the % of positive periods is shown)
import numpy as np
import pandas as pd

def account_metrics(returns, periods_per_year, win_rate=None):
    r = returns.dropna()
    if len(r) < 2:
        return {}
    growth = (1 + r).cumprod()
    years = len(r) / periods_per_year
    if isinstance(r.index, pd.DatetimeIndex) and periods_per_year > 12:
        # daily data can include Sunday bars, so count calendar years and the real number of periods per year
        years = (r.index[-1] - r.index[0]).days / 365.25 + 1 / periods_per_year
        periods_per_year = len(r) / years
    cagr = growth.iloc[-1] ** (1 / years) - 1
    drawdown = growth / growth.cummax() - 1                     # % below the previous high, every period
    max_dd = drawdown.min()
    downside = r[r < 0]
    var_5 = r.quantile(0.05)                                    # 5% of periods are worse than this
    period = "day" if periods_per_year > 12 else "month"
    return {
        "CAGR %": 100 * cagr,
        "Sharpe": r.mean() / r.std() * np.sqrt(periods_per_year) if r.std() > 0 else np.nan,
        # Sortino: like Sharpe, but only the bad periods count as risk
        "Sortino": r.mean() / np.sqrt((np.minimum(r, 0) ** 2).mean()) * np.sqrt(periods_per_year) if len(downside) else np.nan,
        "Max drawdown %": 100 * max_dd,
        # Calmar: yearly return per unit of the worst drawdown
        "Calmar": cagr / -max_dd if max_dd < 0 else np.nan,
        # Omega: total gains / total losses (above / below 0)
        "Omega": r[r > 0].sum() / -downside.sum() if len(downside) else np.nan,
        "Win rate %": win_rate if win_rate is not None else 100 * (r > 0).mean(),
        # Skew > 0: big wins more common than big losses. Kurtosis > 0: more extreme periods than a normal curve
        "Skew": r.skew(),
        "Excess kurtosis": r.kurt(),
        f"5% VaR (per {period}) %": 100 * var_5,
        f"5% CVaR (per {period}) %": 100 * r[r <= var_5].mean(),     # average of the worst 5% of periods
        # Ulcer index: how deep and how long the drawdowns are (root mean square of the % drawdown)
        "Ulcer index": np.sqrt(((100 * drawdown) ** 2).mean()),
        # Recovery factor: total profit / worst drawdown
        "Recovery factor": (growth.iloc[-1] - 1) / -max_dd if max_dd < 0 else np.nan,
    }

def daily_returns_from_equity(equity):
    # equity: account value over time (any bar size) -> daily returns (last value of each day)
    daily = equity.resample("D").last().dropna()
    return daily.pct_change().dropna()
