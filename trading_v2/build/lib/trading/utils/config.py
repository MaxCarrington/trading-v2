import yaml, os
from src.trading.utils.logger import log
import src.trading.utils.constants as constants
CONFIG_FILE_DEFAULT = os.path.join(constants.PROJECT_ROOT, "configs", "backtest_config.yaml")

CONFIG_FILE_DEFAULT_2 = os.path.join(constants.PROJECT_ROOT, "configs", "backtest_config2.yaml")
# Load YAML configs
def load_strategy_configs():
    root = os.path.join(constants.PROJECT_ROOT, "configs")

    thresholds = load_config(os.path.join(root, "strategy_thresholds.yaml"))
    analysis_params = load_config(os.path.join(root, "analysis_parameters.yaml"))
    setup_params = load_config(os.path.join(root , "strategy_setup.yaml"))
    config_path = os.path.join(root, "strategy_labels.yaml")
    config = load_config(config_path)
    labels = config.get("labels", {})

    return thresholds, analysis_params, setup_params, labels

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

# returns the default config file path
def get_config_file_default2():
    return CONFIG_FILE_DEFAULT_2

# Loads config and returns the starting capital value
def get_initial_capital(path=None):
    config = load_config(path or get_config_file_default())
    return config.get("starting_capital", 1_000_000)



