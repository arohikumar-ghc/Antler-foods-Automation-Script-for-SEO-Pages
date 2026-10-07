"""
Logging configuration for the Antler Foods SEO automation.

Provides a single :func:`setup_logging` entry point that configures:
  * a UTF-8, timestamped file handler (DEBUG and above), and
  * a console handler (INFO and above) that is safe for Unicode on Windows.

Never log credentials or other secrets. :meth:`Config.redacted` exists for
safely logging configuration.
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

LOGGER_NAME = "antler_seo"
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def _utf8_console_stream():
    """Return a UTF-8-capable console stream.

    Uses ``sys.stdout`` directly and best-effort reconfigures it to UTF-8 so
    Unicode is safe on Windows code pages. We deliberately do NOT wrap
    ``sys.stdout.buffer`` in a new ``TextIOWrapper`` — doing so detaches the
    stream from test/output-capture machinery and causes "I/O operation on
    closed file" errors at teardown.
    """
    stream = sys.stdout
    reconfigure = getattr(stream, "reconfigure", None)
    if callable(reconfigure):
        try:
            reconfigure(encoding="utf-8")
        except Exception:
            pass
    return stream


def setup_logging(
    log_dir: str = "logs",
    console_level: int = logging.INFO,
    file_level: int = logging.DEBUG,
    log_filename: Optional[str] = None,
) -> logging.Logger:
    """Configure and return the ``antler_seo`` logger.

    Args:
        log_dir: Directory in which to write log files (created if missing).
        console_level: Minimum level emitted to the console.
        file_level: Minimum level written to the log file.
        log_filename: Explicit log file name; defaults to a timestamped name.

    Returns:
        The configured ``antler_seo`` logger. Idempotent: repeat calls replace
        existing handlers rather than stacking duplicates.
    """
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    if log_filename is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_filename = f"antler_seo_{timestamp}.log"

    log_file = log_path / log_filename

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(min(console_level, file_level))

    # Remove any existing handlers so repeat calls don't duplicate output.
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(file_level)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler(_utf8_console_stream())
    console_handler.setLevel(console_level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # Don't propagate to the root logger (avoids duplicate console lines).
    logger.propagate = False

    logger.debug("Logging initialised. Log file: %s", log_file)
    return logger


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """Return the package logger, or a named child logger."""
    if name:
        return logging.getLogger(f"{LOGGER_NAME}.{name}")
    return logging.getLogger(LOGGER_NAME)
