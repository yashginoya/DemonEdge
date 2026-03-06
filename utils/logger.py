import logging
import os
from logging.handlers import RotatingFileHandler

_LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
_LOG_FILE = os.path.join(_LOG_DIR, "terminal.log")
_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DEFAULT_LEVEL = logging.INFO

_initialized = False


def _init_logging(level: int = _DEFAULT_LEVEL) -> None:
    global _initialized
    if _initialized:
        return

    os.makedirs(_LOG_DIR, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(level)

    if not root.handlers:
        console = logging.StreamHandler()
        console.setFormatter(logging.Formatter(_FORMAT))
        root.addHandler(console)

        file_handler = RotatingFileHandler(
            _LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(logging.Formatter(_FORMAT))
        root.addHandler(file_handler)

    _initialized = True


def get_logger(name: str) -> logging.Logger:
    _init_logging()
    return logging.getLogger(name)


def configure_level(level_str: str) -> None:
    """Call this after Config is loaded to apply the configured log level."""
    level = getattr(logging, level_str.upper(), logging.INFO)
    logging.getLogger().setLevel(level)
    _init_logging(level)
