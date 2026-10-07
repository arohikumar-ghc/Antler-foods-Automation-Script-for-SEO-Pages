"""Integration test for the browser lifecycle (Step 8).

Launches real Chromium against about:blank (no Antler UI), captures a
screenshot, and verifies clean startup/shutdown.
"""
import pytest

from antler_seo.automation.browser import BrowserSession
from antler_seo.config import Config


def _config(tmp_path):
    return Config(
        email="test@example.com",
        password="dummy",
        base_url="https://example.com",
        headless=True,
        timeout_ms=15000,
        slow_mo_ms=0,
        logs_dir=str(tmp_path / "logs"),
    )


def test_browser_lifecycle_and_screenshot(tmp_path):
    config = _config(tmp_path)
    session = BrowserSession(config)

    assert not session.is_started

    try:
        page = session.start()
        assert session.is_started

        # Harmless target only — no Antler URL.
        page.goto("about:blank")
        assert page.url == "about:blank"

        shot = session.screenshot("diagnostic.png", full_page=False)
        assert shot is not None
        assert shot.exists()
        assert shot.stat().st_size > 0
    finally:
        session.close()

    assert not session.is_started


def test_context_manager_closes(tmp_path):
    config = _config(tmp_path)
    with BrowserSession(config) as session:
        session.page.goto("about:blank")
        assert session.is_started
    # After the with-block the session must be fully torn down.
    assert not session.is_started


def test_page_access_before_start_raises(tmp_path):
    session = BrowserSession(_config(tmp_path))
    with pytest.raises(RuntimeError):
        _ = session.page


def test_screenshot_before_start_returns_none(tmp_path):
    session = BrowserSession(_config(tmp_path))
    assert session.screenshot("x.png") is None


def test_double_start_raises(tmp_path):
    session = BrowserSession(_config(tmp_path))
    try:
        session.start()
        with pytest.raises(RuntimeError):
            session.start()
    finally:
        session.close()
