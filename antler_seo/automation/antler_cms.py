"""
Antler CMS actions (Antler-UI-specific).

Step 11 scope ONLY:
  * :meth:`AntlerCMS.login`            — authenticate using Config credentials.
  * :meth:`AntlerCMS.select_restaurant`— DYNAMIC tenant selection by name
    (never hard-coded; the name is passed in from the input/batch source).
  * :meth:`AntlerCMS.open_pages`       — navigate WEBSITE → Pages.

Page existence, page creation, and section filling (Steps 13–16) are NOT
implemented here yet.

All selectors come from the central registry
(:mod:`antler_seo.automation.selectors`), captured during the Step 10 UI
investigation. Credentials are read only from :class:`antler_seo.config.Config`
(sourced from ``.env``) — never hard-coded.
"""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from antler_seo.config import Config
from antler_seo.logging_setup import get_logger
from antler_seo.automation import selectors as S
from antler_seo.automation.waits import retry

logger = get_logger("automation.antler_cms")


class AntlerCMSError(Exception):
    """Base error for Antler CMS automation failures."""


class LoginError(AntlerCMSError):
    """Login did not reach the authenticated dashboard."""


class RestaurantSelectionError(AntlerCMSError):
    """The requested restaurant/tenant could not be selected."""


class NavigationError(AntlerCMSError):
    """Navigation to a target screen failed."""


class AntlerCMS:
    """High-level Antler CMS actions driven by a Playwright page.

    The page is supplied by :class:`antler_seo.automation.browser.BrowserSession`
    so this class stays focused on Antler-specific interactions.
    """

    PAGES_PATH = "/dashboard/admin/website/pages-settings"
    HOME_PATH = "/dashboard/admin/home"

    def __init__(self, page: Page, config: Config):
        self.page = page
        self.config = config
        self._origin = _origin_of(config.base_url)
        # Tenant context captured after selecting a restaurant.
        self.restaurant_id: Optional[str] = None
        self.restaurant_name: Optional[str] = None

    # -- authentication -----------------------------------------------------

    def login(self) -> None:
        """Authenticate with the Antler CMS.

        Reads credentials from :class:`Config`. Success is confirmed by the URL
        leaving ``/login`` and reaching the admin dashboard. Cloudflare Turnstile
        is expected to auto-pass in managed mode; if it blocks (we remain on
        ``/login``), a :class:`LoginError` is raised rather than attempting to
        bypass it.
        """
        login_url = self._origin + S.get("auth", "login_url_path").value
        logger.info("Navigating to login page")
        self.page.goto(login_url, wait_until="domcontentloaded")

        email_sel = S.get("auth", "email_field").value
        password_sel = S.get("auth", "password_field").value

        self.page.locator(email_sel).wait_for(
            state="visible", timeout=self.config.timeout_ms
        )
        self.page.locator(email_sel).fill(self.config.email)
        self.page.locator(password_sel).fill(self.config.password)

        # Give managed Turnstile a brief moment to settle before submitting.
        self.page.wait_for_timeout(3500)

        logger.info("Submitting credentials")
        self.page.get_by_role("button", name="Sign In").click()

        try:
            self.page.wait_for_url(
                re.compile(r".*/dashboard/.*"),
                timeout=self.config.timeout_ms,
            )
        except PlaywrightTimeoutError:
            if "/login" in self.page.url:
                raise LoginError(
                    "Still on the login page after submitting credentials. "
                    "This usually means a Cloudflare Turnstile challenge is "
                    "blocking automated login, or the credentials are invalid. "
                    "Re-run non-headless to complete any visible challenge."
                )
            raise LoginError(
                f"Login did not reach the dashboard; current URL: {self.page.url}"
            )

        logger.info("Login successful")

    # -- dynamic restaurant/tenant selection --------------------------------

    def select_restaurant(self, restaurant_name: str) -> str:
        """Select a restaurant/tenant by name (DYNAMIC — never hard-coded).

        Args:
            restaurant_name: The restaurant to open, supplied by the caller
                (ultimately from the input/batch source).

        Returns:
            The captured ``restaurant_id`` for the selected tenant.

        Raises:
            RestaurantSelectionError: If the name is empty or no matching
                suggestion can be selected.
        """
        name = (restaurant_name or "").strip()
        if not name:
            raise RestaurantSelectionError(
                "restaurant_name is required and must be non-empty"
            )

        logger.info("Selecting restaurant: %s", name)

        search_sel = S.get("navigation", "restaurant_search").value

        def _do_select() -> None:
            search = self.page.get_by_placeholder(search_sel)
            search.wait_for(state="visible", timeout=self.config.timeout_ms)
            search.click()
            search.fill("")
            # Type to trigger the suggestion list (filled value alone may not).
            self.page.keyboard.type(name, delay=120)
            self.page.wait_for_timeout(2000)

            option = self.page.get_by_role("button", name=name, exact=True)
            option.first.wait_for(state="visible", timeout=self.config.timeout_ms)
            option.first.click()
            # Tenant context is reflected in the URL query string.
            self.page.wait_for_url(
                re.compile(r".*[?&]restaurant_id=.*"),
                timeout=self.config.timeout_ms,
            )

        try:
            retry(
                _do_select,
                attempts=2,
                base_delay=1.0,
                retry_on=(PlaywrightTimeoutError,),
                description=f"select_restaurant({name})",
            )
        except Exception as exc:
            raise RestaurantSelectionError(
                f"Could not select restaurant {name!r}: {exc}"
            ) from exc

        self.restaurant_id = _restaurant_id_from_url(self.page.url)
        self.restaurant_name = name
        if not self.restaurant_id:
            raise RestaurantSelectionError(
                f"Selected {name!r} but no restaurant_id appeared in the URL"
            )

        logger.info(
            "Restaurant selected: %s (id=%s)", name, self.restaurant_id
        )
        return self.restaurant_id

    # -- navigation ---------------------------------------------------------

    def open_pages(self) -> None:
        """Navigate to WEBSITE → Pages for the selected restaurant.

        Requires a restaurant to have been selected first (so the tenant query
        string is available). Prefers a direct, tenant-scoped URL navigation
        (the most stable path found in investigation) and verifies arrival by
        the presence of the Create Page control.

        Raises:
            NavigationError: If no restaurant is selected or the Pages screen
                does not load.
        """
        if not self.restaurant_id or not self.restaurant_name:
            raise NavigationError(
                "No restaurant selected; call select_restaurant() first"
            )

        url = self._pages_url()
        logger.info("Opening Pages screen")
        self.page.goto(url, wait_until="domcontentloaded")

        try:
            self.page.get_by_role(
                "button", name="Create Page"
            ).first.wait_for(state="visible", timeout=self.config.timeout_ms)
        except PlaywrightTimeoutError as exc:
            raise NavigationError(
                "Pages screen did not load (Create Page control not found)"
            ) from exc

        logger.info("Pages screen ready")

    # -- helpers ------------------------------------------------------------

    def _pages_url(self) -> str:
        """Build the tenant-scoped Pages URL for the current restaurant."""
        from urllib.parse import quote

        return (
            f"{self._origin}{self.PAGES_PATH}"
            f"?restaurant_id={self.restaurant_id}"
            f"&restaurant_name={quote(self.restaurant_name)}"
        )


# --- module-level helpers --------------------------------------------------


def _origin_of(base_url: str) -> str:
    """Return scheme://host[:port] from a configured base URL.

    The configured ``ANTLER_BASE_URL`` may include a path (e.g. ``/login``);
    only the origin is used to build CMS URLs.
    """
    parsed = urlparse(base_url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"Invalid base URL: {base_url!r}")
    return f"{parsed.scheme}://{parsed.netloc}"


def _restaurant_id_from_url(url: str) -> Optional[str]:
    """Extract the ``restaurant_id`` query parameter from a URL, if present."""
    query = urlparse(url).query
    values = parse_qs(query).get("restaurant_id")
    return values[0] if values else None
