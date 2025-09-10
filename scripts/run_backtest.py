import sys, os, yaml
import pandas as pd

from datetime import datetime

from trading.utils.logger import log, start_log
from trading.utils.config import load_config, get_config_file_default

#--------------------------------------------------------------------------------
# Capture command-line arguments
# Argument 0 is the script name
# Argument 1 is --config
# Argument 2 is the config file path (e.g. configs/backtest_config.yaml)
# Run with: python scripts/run_backtest.py --config configs/backtest_config.yaml
#--------------------------------------------------------------------------------

# Pick the provided path if present, otherwise use default
config_path = sys.argv[2] if len(sys.argv) > 2 and sys.argv[1] == "--config" else get_config_file_default()
config = load_config(config_path)

# Set up logging
start_log(config_path, config)
