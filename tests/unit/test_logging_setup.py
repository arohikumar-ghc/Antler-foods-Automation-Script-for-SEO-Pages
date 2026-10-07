"""Unit tests for logging setup (Step 4)."""
import logging

from antler_seo.logging_setup import get_logger, setup_logging


def test_log_file_created_with_unicode(tmp_path):
    log_dir = tmp_path / "logs"
    logger = setup_logging(log_dir=str(log_dir), log_filename="test.log")

    logger.info("Plain ASCII message")
    logger.info("Unicode message: café — 日本語 — ✓ émojis 🚀")
    logger.debug("Debug detail line")

    for handler in logger.handlers:
        handler.flush()

    log_file = log_dir / "test.log"
    assert log_file.exists()

    contents = log_file.read_text(encoding="utf-8")
    assert "Plain ASCII message" in contents
    assert "café — 日本語 — ✓ émojis 🚀" in contents
    # DEBUG goes to the file handler.
    assert "Debug detail line" in contents


def test_setup_is_idempotent(tmp_path):
    log_dir = str(tmp_path / "logs")
    setup_logging(log_dir=log_dir, log_filename="a.log")
    first_count = len(logging.getLogger("antler_seo").handlers)

    setup_logging(log_dir=log_dir, log_filename="b.log")
    second_count = len(logging.getLogger("antler_seo").handlers)

    # Repeat calls replace handlers rather than stacking them.
    assert first_count == second_count == 2


def test_get_logger_returns_child():
    child = get_logger("config")
    assert child.name == "antler_seo.config"
