
# logging_config.py
import os
import logging
from logging.handlers import RotatingFileHandler

LOG_FILE = os.getenv("TUIAI_LOG_FILE", "tuiai.log")
LOG_LEVEL = os.getenv("TUIAI_LOG_LEVEL", "INFO").upper()

# Formatter for all handlers
default_formatter = logging.Formatter(
    "%(asctime)s %(levelname)-8s [%(name)s:%(lineno)d] %(message)s"
)

# Console handler
console_handler = logging.StreamHandler()
console_handler.setLevel(LOG_LEVEL)
console_handler.setFormatter(default_formatter)

# File handler with rotation
file_handler = RotatingFileHandler(
    LOG_FILE,
    maxBytes=10 * 1024 * 1024,
    backupCount=5
)
file_handler.setLevel(LOG_LEVEL)
file_handler.setFormatter(default_formatter)

# Root logger configuration
root_logger = logging.getLogger()
root_logger.setLevel(LOG_LEVEL)
root_logger.addHandler(console_handler)
root_logger.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    """Get a module-specific logger."""
    return logging.getLogger(name)



