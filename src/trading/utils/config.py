import yaml
from pathlib import Path
from src.trading.utils.logger import log

CONFIG_FILE_DEFAULT = Path(__file__).resolve().parents[3] / "configs" / "backtest_config.yaml"

def load_config(path):
    try:
        with open(path, "r") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        log.warning("Config file not found: {}. Using defaults.".format(path))
        return {}
    except yaml.YAMLError as e:
        log.error("YAML parse error in {}: {}".format(path, e))
        raise

# returns the default config file path
def get_config_file_default():
    return CONFIG_FILE_DEFAULT

# Loads config and returns the starting capital value
def get_config_initial_balance(path=None):
    config = load_config(path or get_config_file_default())
    return config.get("starting_capital", 1_000_000)



