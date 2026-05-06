import yaml, os
import trading.utils.constants as constants

from trading.utils.logger import info, warning, error

CONFIGS_DIR = constants.CONFIGS_DIR
import trading.utils.constants as constants
# Loads a YAML config file from the given path.
# - Returns the parsed config as a dictionary
# - Raises an error if the file is missing or the YAML format is invalid
def load_config(config_file):
    info(f"Current file is {__file__}")
    path = os.path.join(CONFIGS_DIR, config_file)
    try:
        with open(path, "r") as f:
            info("Loaded config from {}".format(path))
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        error("Config file not found: {}. Using defaults.".format(path), __file__)
        raise FileNotFoundError
    except yaml.YAMLError as e:
        error("YAML parse error in {}: {}".format(path, e), __file__)
        raise e

def get_config_file_default():
    info(f"Current file is {__file__}")
    path = constants.CONFIG_DEFAULT
    try:
        with open(path, "r") as f:
            info("Loaded config from {}".format(path))
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        error("Config file not found: {}. Using defaults.".format(path), __file__)
        raise FileNotFoundError
    except yaml.YAMLError as e:
        error("YAML parse error in {}: {}".format(path, e), __file__)
        raise e

