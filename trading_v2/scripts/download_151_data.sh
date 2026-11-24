#!/bin/bash
# Downloads all daily data for the "151 Trading Strategies" tests that OANDA and IBKR can give us.
# Run from the trading_v2 folder:   bash scripts/download_151_data.sh
# The IBKR part needs IB Gateway running (paper, port 4002) and Client Portal / the phone app logged out.
# Downloading 2019-2026 is fine: tests still only use the dates in each strategy's config (2005-2018).
set -u
export PYTHONPATH=src
PERIOD=2005-01-01,2026-10-22

echo "=== OANDA: commodities (9.3, 10.4 trend following) ==="
python scripts/generate_backtest_data.py --data forex --period $PERIOD --timeframe D \
  --tickers XAU_USD,XAG_USD,XPT_USD,XPD_USD,XCU_USD,WTICO_USD,BCO_USD,NATGAS_USD,CORN_USD,WHEAT_USD,SOYBN_USD,SUGAR_USD

echo "=== OANDA: government bonds (5.11-5.13 yield curve) ==="
python scripts/generate_backtest_data.py --data forex --period $PERIOD --timeframe D \
  --tickers USB02Y_USD,USB05Y_USD,USB10Y_USD,USB30Y_USD,DE10YB_EUR,UK10YB_GBP

echo "=== OANDA: other stock indices (4.6 multi-asset trend) ==="
python scripts/generate_backtest_data.py --data forex --period $PERIOD --timeframe D \
  --tickers NAS100_USD,US30_USD,US2000_USD,JP225_USD,AU200_AUD,HK33_HKD,CN50_USD,EU50_EUR

echo "=== IBKR: ETFs and the VIX ==="
python scripts/ibkr_download.py data/ibkr_download_151.yaml
