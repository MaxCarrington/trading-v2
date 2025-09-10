import os
import logging
from datetime import datetime
from typing import Optional, Dict

from trading.utils.paths import get_logs_dir


# Ensure logs directory exists
LOGS_DIR = get_logs_dir()
os.makedirs(LOGS_DIR, exist_ok=True)


def _default_logger() -> logging.Logger:
    logger = logging.getLogger("trading")
    logger.setLevel(logging.INFO)
    # If handlers already configured (e.g. in tests or application), keep them
    if not logger.handlers:
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")
        ch.setFormatter(fmt)
        logger.addHandler(ch)
    return logger


# public logger instance
log = _default_logger()


def start_log(config_path: Optional[str] = None, config: Optional[Dict] = None, *, name_prefix: str = "backtest"):
    """(Re)configure the module logger and add a file handler.

    Creates a timestamped logfile under `LOGS_DIR`. If `config_path` is provided,
    its base name is used as part of the logfile name.
    """
    global log

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    if config_path:
        base = os.path.splitext(os.path.basename(config_path))[0]
        filename = f"{base}_{ts}.log"
    else:
        filename = f"{name_prefix}_{ts}.log"

    log_path = os.path.join(LOGS_DIR, filename)

    # Remove existing FileHandlers to avoid duplicate writes
    for h in list(log.handlers):
        if isinstance(h, logging.FileHandler):
            log.removeHandler(h)

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")

    try:
        fh = logging.FileHandler(log_path)
        fh.setLevel(logging.INFO)
        fh.setFormatter(fmt)
        log.addHandler(fh)
    except Exception:
        # If file can't be opened, keep running with console only
        log.warning(f"Could not open log file for writing: {log_path}")

    # Optionally print config to log
    if config_path:
        log.info(f"Using config file: {config_path}")
    if config is not None:
        try:
            import yaml

            text = yaml.safe_dump(config, sort_keys=False, default_flow_style=False).rstrip()
        except Exception:
            import json

            text = json.dumps(config, indent=2)
        for line in text.splitlines():
            log.info(line)

    log.info(f"Logging started — file={log_path}")


# convenience wrappers
def message(msg: str):
    log.info(msg)


def info(msg: str):
    log.info(msg)


def warning(msg: str):
    log.warning(msg)


def error(msg: str):
    log.error(msg)
