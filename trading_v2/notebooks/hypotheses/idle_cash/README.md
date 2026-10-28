# Idle-cash FX hypotheses H17-H44: results (research period 2005-18 only)

The ideas come from `fx_hypotheses_for_idle_cash.md`. Each H number = 16 + the idea's number.

**How each test was run:**
- The rule and its variants were written down before running, then run once on 2005-18 (no 2019+ data loaded).
- **Costs:**
  - Spread: today's OANDA spread, the median 2016-18 H1 spread during 07-17 London.
  - Slippage: 0.3 pips per side.
  - Swap: the rate gap minus a 1.5%/yr markup, per night held.
- **Pass rules:** net t > 2, at least 60% of years positive, positive without the best year, beats 95% of random entries, and at least 30 trades.
- **Luck bar:** with 22 ideas tested, about one would pass t > 2 by luck. The "luck-proof" bar is t > 2.84.
- **"Idle"** = the trades that start and end inside the free window (trading day 4 to 5 days before month end).
- Shared helper: `src/trading/research/fx_hypothesis_tools.py`. Configs: `configs/analysis/idle_cash/`.

## Results

| H | Idea | Result | Trades | Net pips/trade | t | Years + | Idle window |
|---|---|---|---|---|---|---|---|
| 17 | Non-US central bank pre-meeting drift | FAIL | 807 | −0.8 | −0.19 | 43% | −5.4, t −0.97 |
| 18 | Fade the move after a central bank decision | FAIL | 61 | −31.8 | −3.14 | 21% | −36.1 |
| 19 | Gotobi days, USD/JPY into the Tokyo fix | FAIL | 1002 | −1.3 | −2.65 | 21% | −0.3 (gross +0.7 vs cost 2.0) |
| 20 | Japanese fiscal year end (yen) | FAIL | 42 | −125.8 | −3.38 | 29% | no trades |
| 21 | Fade big moves on holidays | FAIL | 23 | −27.7 | −1.49 | 40% | 4 trades |
| 22 | FX options expiry pinning | NOT TESTABLE | - | - | - | - | no historical expiry data |
| 23 | US yield moves lead USD/JPY | FAIL | 604 | −2.2 | −0.39 | 43% | −11.1 |
| 24 | Commodity currencies vs oil/copper/gold | NOT RUN | needs data | | | | |
| 25 | USD/JPY vs US 10-year residual fade | FAIL | 41 | +14.4 | 0.42 | 55% | 6 trades |
| 26 | Big S&P / Nikkei day → JPY crosses next day | FAIL | 516 | −15.8 | −2.96 | 25% | −12.5 (moves partly reverse, not continue) |
| **27** | **Month-end stock gap → buy USD into month end** | **PASS (not luck-proof)** | 120 | **+36.3** | **2.20** | **85%** | **no trades: it sits inside the month-end window** |
| 28 | Gold vs the dollar | NOT RUN | needs full XAU_USD | | | | |
| 29 | AUD/NZD mean reversion | FAIL | 148 | −5.9 | −0.46 | 50% | −6.4 (half-life ~1 year: it trends) |
| 30 | EUR/CHF range (floor years skipped) | FAIL | 110 | −2.7 | −0.21 | 55% | +6.6, t 0.49 |
| 31 | USD/CAD vs oil fair value | NOT RUN | only if H24 passes | | | | |
| 32 | CAD/CHF, AUD/CAD mean reversion | NOT RUN | only if H29 passed (it failed) | | | | |
| 33 | OANDA retail position book, contrarian | NOT RUN | needs OANDA snapshots | | | | |
| 34 | OANDA order book stop clusters | NOT RUN | needs OANDA snapshots | | | | |
| 35 | Weekend gap fade | FAIL in practice | 897 | +6.5 (t 4.03 at mid prices) | | 79% | at the real first quotes net +0.2, t 0.12 |
| 36 | Volatility-scaled sizing | DEMO | - | - | - | - | trims crash losses, can't create an edge |
| 37 | Narrow-range breakout, daily | FAIL | 385 | +1.0 | 0.14 | 50% | +12.1, t 1.46 |
| 38 | VIX vs realised vol regime, AUD/JPY | NOT RUN | needs FRED VIXCLS | | | | |
| 39 | USD drift days 4-15 of the month | FAIL | 1176 | −15.9 | −2.20 | 29% | same as all trades |
| 40 | Day of week | FAIL | 5095 | −5.8 | −5.59 | 29% | 0 of 70 weekday cells significant |
| 41 | Pre-NFP USD drift | FAIL | 664 | +4.6 | 1.46 | 64% | +8.5, t 1.95 (close) |
| 42 | Month-of-year seasonality | FAIL | 195 | +8.2 | 0.35 | 43% | 0 of 168 cells significant |
| 43 | Carry in the idle window, calm markets | FAIL | 332 | −3.0 | −0.29 | 46% | same as all trades |
| 44 | Risk-off month → JPY crosses next idle window | FAIL | 156 | −9.7 | −0.31 | 46% | same; swap −17 per trade |

## What we learnt

- **Nothing tradeable with idle cash passed.** Short calendar and event holds either have no edge, or have one smaller than spread + slippage + swap (about 2-2.5 pips plus swap).
- **Big event moves keep going (H18, H21, H26).** Fading them loses. This was found after the fact, so it is a new idea to pre-register, not a result.
- **H27 is the one real candidate.**
  - In months where US stocks lag bonds by 2%+ at the signal day, the dollar rises into month end, on all three pairs.
  - Also: the mirror (gap ≥ +2%, sell USD) is positive too (t 2.43), all months together give t 2.68, and correlation with the index trade is 0.05.
  - Weak spots: the three pairs are really one USD bet (about 40 independent months), and it doesn't clear the luck-proof bar.
  - It isn't idle cash. It would run alongside the month-end index trade, using spare margin.
  - Next step: one validation run on 2019-22, unchanged.
- **H35 lesson:** an edge at the first quote of a session is usually the spread. Always check the real bid/ask.

## Data to download for the NOT RUN ones (on the Mac)

```
python scripts/generate_backtest_data.py --data forex --period 2005-01-01,2018-12-31 --timeframe D --tickers WTICO_USD,BCO_USD,XCU_USD,XAU_USD,USD_NOK
python scripts/generate_backtest_data.py --data forex --period 2016-01-01,2018-12-31 --timeframe H1 --tickers XAU_USD,USD_NOK
```

- **VIXCLS:** https://fred.stlouisfed.org/graph/fredgraph.csv?id=VIXCLS, saved to `data/long_history/VIXCLS.csv`.
- **NOK rate:** FRED IR3TIB01NOM156N, saved to `data/rates/NOK.csv`.
- **H33 / H34:** run their first cells on the Mac. They ask OANDA how far back its books go.

`data/cb_meetings.csv`: 894 central bank decision dates for 2004-18 (ECB, BoE, BoJ, RBA, BoC, SNB), all taken from official pages. Sources and caveats are in `data/cb_meetings_README.md`.

# Batch 2: H45-H61 (rules in `fx_hypotheses_batch2.md`, 39 ideas tested in total, luck-proof bar t > 3.02)

| H | Idea | Result | Trades | Net pips/trade | t | Years + | Idle-only (enter on idle days, exit by the last idle day) |
|---|---|---|---|---|---|---|---|
| 45 | Big daily move (>2.5x ATR) continues 3 days | FAIL | 90 | +15.2 | 0.75 | 54% | −7.1, t −0.24 |
| 46 | Central bank decision-day move continues | FAIL | 219 | −0.9 | −0.10 | 57% | −6.7 |
| 47 | Bund vs Treasury spread → EUR/USD | FAIL | 163 | +18.7 | 1.12 | 57% | +29.8, t 1.62 (68% of pips from 2008) |
| 48 | Gilt vs Treasury spread → GBP/USD | FAIL | 191 | +14.8 | 0.99 | 79% | −5.5 |
| 49 | Nikkei vs USD/JPY residual fade | FAIL | 40 | +12.2 | 0.29 | 55% | +23.4, t 0.65 |
| 50 | AUD/JPY vs S&P residual fade | FAIL | 47 | −28.7 | −0.55 | 55% | −15.1 |
| 51 | Weekly currency strength reversal | FAIL | 1140 legs | −6.6 | −1.22 | 21% | −6.2 |
| 52 | Combination of near-misses (info only) | INFO | 168 months | +12.3/month | 1.64 | 71% | components chosen after the fact |
| 53 | Monday reverses a big Friday | FAIL (wrong way) | 1101 | −10.1 | −3.52 | 36% | big Fridays continue |
| 54 | Big week reverses next week | FAIL (wrong way) | 378 | −16.8 | −1.15 | 31% | big weeks continue |
| 55 | Bollinger fade in range-bound pairs | FAIL | 484 | −9.8 | −0.95 | 39% | +2.0, t 0.17 |
| 56 | RSI(2) dip/rip with 200-day trend | FAIL (closest) | 787 | +8.0 | 1.29 | 50% | +4.8, t 0.74 (gross +12.8, beats 98% random) |
| 57 | Fade after a volatility spike | FAIL | 211 | +6.0 | 0.32 | 57% | −28.3 |
| 58 | New 52-week high/low continues | FAIL | 568 | +14.7 | 1.15 | 43% | +18.4, t 1.49 (2008 = 80% of pips) |
| 59 | Fade 4-day streaks | FAIL | 2133 | −8.3 | −2.53 | 43% | −8.9 |
| 60 | US 10y 20-day trend → USD/JPY | FAIL | 176 | −13.6 | −0.85 | 39% | −20.6 |
| 61 | Short USD before US holidays | FAIL (wrong way) | 973 | −7.9 | −3.78 | 29% | USD rose before holidays |

**Batch 2 lessons:**
- **Short-term FX moves continue, they don't reverse.** Every fade lost: Monday-after-Friday, big weeks, streaks, strength reversal. Trend-type ideas made money gross, but mostly in 2008, and swap ate most of the rest.
- **No new candidate.** H27 (batch 1) is still the only idea that passed, and it trades inside the month-end window, not with idle cash.
