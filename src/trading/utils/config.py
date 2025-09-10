import yaml

from trading.utils.logger import log

CONFIG_FILE_DEFAULT = "configs/backtest_config.yaml"  # default config file

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
    
def get_config_file_default():
    return CONFIG_FILE_DEFAULT