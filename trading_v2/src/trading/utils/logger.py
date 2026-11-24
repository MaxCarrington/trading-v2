import os
import logging
from datetime import datetime
from typing import Optional, Dict
import colorlog
from trading.utils.paths import get_logs_dir


# Default (date-bucketed) log location. Actual directory creation is lazy —
# it happens inside start_log() when a log file is actually opened, not at
# import time — so importing this module no longer creates an empty
# logs/<date>/ folder on every run.
DEFAULT_LOG_DIR = get_logs_dir()
todays_date = datetime.now().strftime("%Y%m%d")
LOG_DIR = os.path.join(DEFAULT_LOG_DIR, todays_date)

def _default_logger() -> logging.Logger:
    logger = logging.getLogger("trading")
    logger.setLevel(logging.INFO)

    if not logger.handlers:
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)

        formatter = colorlog.ColoredFormatter(
            "%(log_color)s%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
            log_colors={
                "DEBUG": "white",
                "INFO": "white",
                "WARNING": "yellow",
                "ERROR": "red",
                "CRITICAL": "red",
            },
        )

        ch.setFormatter(formatter)
        logger.addHandler(ch)

    return logger

# public logger instance
log = _default_logger()

def start_log(
    config_path: Optional[str] = None,
    config: Optional[Dict] = None,
    *,
    name_prefix: str = "backtest",
    log_subdir: Optional[str] = None,
    log_dir: Optional[str] = None,   # 👈 NEW: explicit directory override (e.g. a run folder)
    filename: Optional[str] = None,  # 👈 NEW: explicit filename override (e.g. "run.log")
):
    global log

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Filename: explicit override wins, otherwise fall back to the old
    # config-based / auto-timestamped naming.
    if filename is None:
        if config_path:
            base = os.path.splitext(os.path.basename(config_path))[0]
            filename = f"{base}_{ts}.log"
        else:
            filename = f"{name_prefix}_{ts}.log"

    # Directory: explicit override wins (e.g. a per-run results folder),
    # otherwise fall back to the date-bucketed default logs/ tree.
    if log_dir is None:
        if log_subdir:
            log_dir = os.path.join(LOG_DIR, log_subdir)
        else:
            log_dir = LOG_DIR

    os.makedirs(log_dir, exist_ok=True)

    log_path = os.path.join(log_dir, filename)

    # Remove existing FileHandlers
    for h in list(log.handlers):
        if isinstance(h, logging.FileHandler):
            log.removeHandler(h)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        "%Y-%m-%d %H:%M:%S",
    )

    try:
        fh = logging.FileHandler(log_path)
        fh.setLevel(logging.INFO)
        fh.setFormatter(fmt)
        log.addHandler(fh)
    except Exception:
        log.warning(f"Could not open log file for writing: {log_path}")

    log.info(f"Logging started. Log file location={log_path}")

# convenience wrappers
def message(msg: str, file=None):
    if file is not None:
        log.info(f"{msg}.       File location: {file}")
    else:
        log.info(f"{msg}")


def info(msg: str, file=None):
    if file is not None:
        log.info(f"{msg}.       File location: {file}")
    else:
        log.info(f"{msg}")


def warning(msg: str, file=None):
    if file is not None:
        log.warning(f"{msg}.       File location: {file}")
    else:
        log.warning(f"{msg}")


def error(msg: str, file=None):
    if file is not None:
        log.error(f"{msg}.       File location: {file}")
    else:
        log.error(f"{msg}")

