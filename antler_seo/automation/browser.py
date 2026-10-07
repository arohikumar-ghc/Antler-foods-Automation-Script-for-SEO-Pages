"""
Playwright browser lifecycle (framework-agnostic).

Manages the Playwright → Browser → Context → Page stack for Chromium, applying
headless / timeout / slow-mo from :class:`antler_seo.config.Config`. Provides a
screenshot helper for diagnostics and clean shutdown (usable as a context
manager).

This module contains NO Antler-UI knowledge — no URLs, selectors, login,
navigation or page logic. Those live in ``antler_cms.py`` and are implemented
only after the Antler UI investigation (Phase 4).
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    sync_playwright,
)

from antler_seo.config import Config
from antler_seo.logging_setup import get_logger

logger = get_logger("automation.browser")


class BrowserSession:
    """Owns a single Chromium browser session.

    Typical use::

        with BrowserSession(config) as session:
            session.page.goto("about:blank")
            session.screenshot("diagnostic.png")

    Or explicitly::

        session = BrowserSession(config)
        session.start()
        ...
        session.close()
    """

    def __init__(self, config: Config, screenshots_dir: Optional[str] = None):
        """Initialise the session (does not launch the browser).

        Args:
            config: Runtime configuration (headless, timeout, slow-mo, logs dir).
            screenshots_dir: Where screenshots are written; defaults to the
                configured logs directory.
        """
        self.config = config
        self.screenshots_dir = Path(screenshots_dir or config.logs_dir)

        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

    # -- lifecycle ----------------------------------------------------------

    def start(self) -> Page:
        """Launch Chromium and create a context and page.

        Returns:
            The active :class:`Page`.

        Raises:
            RuntimeError: If the session is already started.
        """
        if self._playwright is not None:
            raise RuntimeError("BrowserSession is already started")

        logger.info(
            "Starting Chromium (headless=%s, timeout=%dms, slow_mo=%dms)",
            self.config.headless,
            self.config.timeout_ms,
            self.config.slow_mo_ms,
        )

        self._playwright = sync_playwright().start()
        try:
            self._browser = self._playwright.chromium.launch(
                headless=self.config.headless,
                slow_mo=self.config.slow_mo_ms,
            )
            self._context = self._browser.new_context()
            self._page = self._context.new_page()
            self._page.set_default_timeout(self.config.timeout_ms)
        except Exception:
            # Ensure Playwright is stopped if partial startup fails.
            self.close()
            raise

        logger.info("Chromium started")
        return self._page

    def close(self) -> None:
        """Close page, context, browser and Playwright. Safe to call twice."""
        for name, closer in (
            ("page", self._page),
            ("context", self._context),
            ("browser", self._browser),
        ):
            if closer is not None:
                try:
                    closer.close()
                except Exception as exc:  # pragma: no cover - defensive
                    logger.warning("Error closing %s: %s", name, exc)

        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Error stopping Playwright: %s", exc)

        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None
        logger.info("Browser session closed")

    # -- context manager ----------------------------------------------------

    def __enter__(self) -> "BrowserSession":
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    # -- accessors ----------------------------------------------------------

    @property
    def is_started(self) -> bool:
        return self._page is not None

    @property
    def page(self) -> Page:
        if self._page is None:
            raise RuntimeError("BrowserSession is not started; call start()")
        return self._page

    @property
    def context(self) -> BrowserContext:
        if self._context is None:
            raise RuntimeError("BrowserSession is not started; call start()")
        return self._context

    @property
    def browser(self) -> Browser:
        if self._browser is None:
            raise RuntimeError("BrowserSession is not started; call start()")
        return self._browser

    # -- diagnostics --------------------------------------------------------

    def screenshot(self, filename: str, full_page: bool = True) -> Optional[Path]:
        """Capture a screenshot into the screenshots directory.

        Args:
            filename: File name (a ``.png`` suffix is added if missing).
            full_page: Whether to capture the full scrollable page.

        Returns:
            The path written, or ``None`` if the session isn't started or the
            capture failed (screenshots must never crash the caller).
        """
        if self._page is None:
            logger.warning("Cannot screenshot: session not started")
            return None

        if not filename.lower().endswith(".png"):
            filename = f"{filename}.png"

        self.screenshots_dir.mkdir(parents=True, exist_ok=True)
        path = self.screenshots_dir / filename

        try:
            self._page.screenshot(path=str(path), full_page=full_page)
            logger.info("Screenshot saved: %s", path)
            return path
        except Exception as exc:
            logger.warning("Failed to capture screenshot: %s", exc)
            return None

    @staticmethod
    def timestamped_name(prefix: str) -> str:
        """Return a timestamped screenshot name like ``prefix_YYYYmmdd_HHMMSS``."""
        return f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
