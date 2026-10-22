"""
Antler CMS actions (Antler-UI-specific).

Implemented:
  * :meth:`AntlerCMS.login`             — authenticate using Config credentials.
  * :meth:`AntlerCMS.select_restaurant` — DYNAMIC tenant selection by name
    (never hard-coded; the name comes from the input/batch source).
  * :meth:`AntlerCMS.open_pages`        — navigate WEBSITE → Pages.
  * :meth:`AntlerCMS.page_exists`       — idempotency check against the list.
  * :meth:`AntlerCMS.create_seo_page`   — create a page + Custom section + FAQ
    section, then publish; returns a :class:`antler_seo.models.PageResult`.

All selectors come from the central registry
(:mod:`antler_seo.automation.selectors`), captured during the Step 10 UI
investigation. Credentials are read only from :class:`antler_seo.config.Config`
(sourced from ``.env``) — never hard-coded.

Content mapping (Antler has no separate social fields; the investigation
confirmed Meta Title/Description double as the social preview):
  * Meta Title       ← SEOPage.seo_title
  * Meta Description ← SEOPage.seo_description
  * Custom section: Headline ← title, Subheadline ← subtitle, Description ← description
  * FAQ section: each FAQ question/answer
Images are NOT handled (no verified upload flow); this is recorded, not guessed.
"""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from antler_seo.config import Config
from antler_seo.logging_setup import get_logger
from antler_seo.models import (
    PageResult,
    SEOPage,
    SECTION_BASIC_INFO,
    SECTION_SEO_METADATA,
    SECTION_CONTENT,
    SECTION_FAQ,
)
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


class PageCreationError(AntlerCMSError):
    """A critical page-creation step failed (basic info / SEO shell)."""


class SessionUnusableError(AntlerCMSError):
    """The browser session is no longer usable (closed or bounced to login)."""


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

    # -- session health -----------------------------------------------------

    def is_session_alive(self) -> bool:
        """True if the browser session still looks authenticated/usable.

        A closed page, or a URL bounced back to ``/login``, means the session is
        no longer usable (e.g. auth expired). Used by the orchestrator to stop
        the batch safely instead of re-attempting login per restaurant.
        """
        try:
            if self.page.is_closed():
                return False
            return "/login" not in (self.page.url or "")
        except Exception:
            return False

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

    # -- idempotency / row matching ----------------------------------------

    _JS_FIND_BY_SLUG = """
    (slug) => {
      const trs = Array.from(document.querySelectorAll('table tbody tr'));
      for (let i = 0; i < trs.length; i++) {
        const tds = trs[i].querySelectorAll('td');
        if (tds.length > 1 && (tds[1].innerText || '').trim() === slug) return i;
      }
      return -1;
    }
    """

    _JS_FIND_BY_NAME = """
    (name) => {
      const trs = Array.from(document.querySelectorAll('table tbody tr'));
      for (let i = 0; i < trs.length; i++) {
        const tds = trs[i].querySelectorAll('td');
        const first = tds.length ? (tds[0].innerText || '').trim().split('\\n')[0].trim() : '';
        if (first === name) return i;
      }
      return -1;
    }
    """

    _JS_SLUG_PRESENT = """
    (slug) => {
      const trs = Array.from(document.querySelectorAll('table tbody tr'));
      for (const tr of trs) {
        const tds = tr.querySelectorAll('td');
        if (tds.length > 1 && (tds[1].innerText || '').trim() === slug) return true;
      }
      return false;
    }
    """

    def _row_index(self, page_name: str, href: str) -> int:
        """0-based Pages-table row index matching the exact slug (preferred) or
        exact page name, else -1."""
        slug = _normalize_slug(href)
        if slug:
            idx = self.page.evaluate(self._JS_FIND_BY_SLUG, slug)
            if idx is not None and idx >= 0:
                return idx
        name = (page_name or "").strip()
        if name:
            idx = self.page.evaluate(self._JS_FIND_BY_NAME, name)
            if idx is not None and idx >= 0:
                return idx
        return -1

    def page_exists(self, page_name: str, href: str = "") -> bool:
        """Exact match on the URL-slug cell (preferred) or page-name cell.

        The Pages screen must already be open.
        """
        return self._row_index(page_name, href) >= 0

    def row_status(self, page_name: str, href: str) -> Optional[str]:
        """STATUS cell text (e.g. 'Draft'/'Published') for the row, else None."""
        idx = self._row_index(page_name, href)
        if idx < 0:
            return None
        cells = self.page.locator("table tbody tr").nth(idx).locator("td")
        return (cells.nth(2).inner_text() or "").strip() if cells.count() >= 3 else None

    # -- section-presence verification (registry-backed drag handle) --------

    def _section_count(self) -> int:
        title = S.get("finalization", "section_drag_handle").value
        return self.page.locator(f"[title='{title}']").count()

    def _wait_section_added(self, before_count: int) -> None:
        """Confirm a section actually saved: it now appears in Active Sections
        (drag-handle count increased). Raises PageCreationError on timeout."""
        title = S.get("finalization", "section_drag_handle").value
        try:
            self.page.wait_for_function(
                "(a) => document.querySelectorAll(\"[title='\" + a.t + \"']\").length > a.n",
                arg={"t": title, "n": before_count},
                timeout=self.config.timeout_ms,
            )
        except PlaywrightTimeoutError as exc:
            raise PageCreationError(
                "Section save not confirmed (Active Sections count did not "
                "increase)"
            ) from exc

    def _click_section_category(self, group: str, name: str) -> None:
        """Select a section category via the REGISTRY entry (primary text, then
        recorded positional fallback)."""
        sel = S.get(group, name)
        if sel.value:
            loc = self.page.get_by_text(sel.value, exact=False)
            try:
                loc.first.wait_for(state="visible", timeout=self.config.timeout_ms)
                loc.first.click()
                return
            except PlaywrightTimeoutError:
                pass
        if sel.fallback:
            self.page.locator(sel.fallback).first.click()
            return
        raise PageCreationError(f"Could not select section category: {group}.{name}")

    # -- page creation ------------------------------------------------------

    def create_seo_page(self, data: SEOPage, publish: bool = False) -> PageResult:
        """Create one SEO page end-to-end and return a :class:`PageResult`.

        Flow: idempotency check → Create Page modal (basic info + SEO meta) →
        open editor → Custom section → FAQ section. Publishes only when
        ``publish=True`` AND both content and FAQ sections saved. ``success``
        requires every attempted section saved; a critical failure → ``failed``;
        an optional-section failure → ``partial``. Section problems are captured
        on the result (not raised) so a batch can continue.
        """
        logger.info("Creating SEO page: %s (%s)", data.page_name, data.href)

        if data.image is not None:
            logger.info(
                "Image present for %s but no verified Antler image-upload flow; "
                "image not processed (text/FAQ only).",
                data.page_name,
            )

        # Ensure we start from this restaurant's Pages list: after creating/
        # editing a prior page the browser is left in the editor, where the
        # "Create Page" control does not exist. open_pages() re-navigates to the
        # tenant-scoped Pages URL (reusing the verified navigation). A failure
        # here is reported as a failed page rather than letting a later click
        # wait out its full timeout.
        try:
            self.open_pages()
        except Exception as exc:
            logger.error("Could not open Pages list for %s: %s", data.page_name, exc)
            return PageResult.failed_result(
                data.page_name, data.href,
                error=f"Could not open Pages list: {exc}",
            )

        if self.page_exists(data.page_name, data.href):
            logger.info("Page already exists, skipping: %s", data.page_name)
            return PageResult.skipped_result(data.page_name, data.href)

        sections: dict[str, bool] = {}

        try:
            self._create_page_shell(data)
            sections[SECTION_BASIC_INFO] = True
            sections[SECTION_SEO_METADATA] = True
        except Exception as exc:
            logger.error("Create-page shell failed for %s: %s", data.page_name, exc)
            return PageResult.failed_result(
                data.page_name,
                data.href,
                error=f"Create page failed: {exc}",
                sections={SECTION_BASIC_INFO: False, SECTION_SEO_METADATA: False},
            )

        try:
            self._open_page_editor(data)
        except Exception as exc:
            logger.error("Opening editor failed for %s: %s", data.page_name, exc)
            return PageResult.from_sections(
                data.page_name, data.href, sections,
                error=f"Editor did not open: {exc}",
            )

        try:
            self._add_custom_section(data)
            sections[SECTION_CONTENT] = True
        except Exception as exc:
            sections[SECTION_CONTENT] = False
            logger.error("Custom section failed for %s: %s", data.page_name, exc)

        try:
            self._add_faq_section(data)
            sections[SECTION_FAQ] = True
        except Exception as exc:
            sections[SECTION_FAQ] = False
            logger.error("FAQ section failed for %s: %s", data.page_name, exc)

        error = None
        if publish:
            if sections.get(SECTION_CONTENT) and sections.get(SECTION_FAQ):
                try:
                    self._publish_page()
                except Exception as exc:
                    error = f"Publish failed: {exc}"
                    logger.error("Publish failed for %s: %s", data.page_name, exc)
            else:
                error = "Not published: a required section was incomplete"
                logger.warning("%s: %s", data.page_name, error)

        result = PageResult.from_sections(
            data.page_name, data.href, sections, error=error
        )
        logger.info("Page %s -> %s", data.page_name, result.status)
        return result

    def _create_page_shell(self, data: SEOPage) -> None:
        """Open the Create Page modal and fill basic info + SEO metadata."""
        self.page.get_by_role("button", name="Create Page").first.click()

        name_field = self.page.locator(S.get("page", "create_modal_name").value)
        name_field.wait_for(state="visible", timeout=self.config.timeout_ms)
        name_field.fill(data.page_name)
        self.page.locator(S.get("page", "create_modal_slug").value).fill(
            _normalize_slug(data.href).lstrip("/")
        )
        # Antler has no separate social fields; Meta ← SEO (confirmed Step 10).
        self.page.locator(S.get("page", "create_modal_meta_title").value).fill(
            data.seo_title
        )
        self.page.locator(
            S.get("page", "create_modal_meta_description").value
        ).fill(data.seo_description)
        logger.info(
            "No separate social metadata UI in Antler; using SEO title/"
            "description for Meta Title/Description."
        )

        self.page.locator("form").get_by_role(
            "button", name="Create Page"
        ).click()

        self.page.wait_for_function(
            self._JS_SLUG_PRESENT,
            arg=_normalize_slug(data.href),
            timeout=self.config.timeout_ms,
        )

    def _open_page_editor(self, data: SEOPage) -> None:
        """Open the editor for the just-created page from the Pages list."""
        idx = self._row_index(data.page_name, data.href)
        if idx < 0:
            raise PageCreationError(
                f"Created page not found in list to open editor: {data.page_name}"
            )
        self.page.locator("table tbody tr").nth(idx).locator(
            S.get("page", "row_edit_button").value
        ).first.click()
        self.page.wait_for_url(
            re.compile(r".*/admin/page-settings.*page_id=.*"),
            timeout=self.config.timeout_ms,
        )
        self.page.get_by_role("button", name="Add Section").first.wait_for(
            state="visible", timeout=self.config.timeout_ms
        )

    def _enable_scroll_animation(self) -> None:
        """Ensure the custom section's 'Page Scroll Animation' toggle is ON.

        The toggle is a native ``<input type=checkbox>`` whose visible control is
        a visually-hidden (sr-only) input inside a ``<label>`` row anchored by a
        unique 'Page Scroll Animation' heading. We confirm the heading is unique
        BEFORE waiting on it, locate its row and checkbox, read the current
        state, click the row's ``<label>`` ONLY if it is OFF (never blindly, so
        an already-enabled toggle is left ON), then verify it is ON. A missing,
        ambiguous, or unverifiable toggle raises :class:`PageCreationError`
        rather than continuing silently.
        """
        label_text = S.get("content", "typography_scroll_animation_label").value
        heading = self.page.get_by_text(label_text, exact=True)

        # Safeguard 1: verify uniqueness BEFORE waiting/interacting.
        hcount = heading.count()
        if hcount != 1:
            raise PageCreationError(
                f"'Page Scroll Animation' label matched {hcount} elements "
                f"(expected 1); refusing to toggle an ambiguous or missing "
                f"control."
            )
        try:
            heading.wait_for(state="visible", timeout=self.config.timeout_ms)
        except PlaywrightTimeoutError as exc:
            raise PageCreationError(
                f"'Page Scroll Animation' toggle not visible ({label_text!r})."
            ) from exc

        # The toggle lives in the heading's row (the nearest ancestor that also
        # holds the checkbox). Scope the checkbox to that row so we never touch
        # one of the other checkboxes on the builder.
        row = heading.locator(
            "xpath=ancestor::*[.//input[@type='checkbox']][1]"
        )
        input_sel = S.get("content", "typography_scroll_animation_input").value
        checkbox = row.locator(input_sel)
        cb_count = checkbox.count()
        if cb_count != 1:
            raise PageCreationError(
                f"Expected exactly one Page Scroll Animation checkbox in its "
                f"row, found {cb_count}."
            )

        if not checkbox.is_checked():
            # Safeguard 2: the <input> is sr-only; click the wrapping <label>
            # (its real hit target). Require exactly one label — never fall back
            # to clicking the hidden checkbox.
            label_control = row.locator("label")
            lbl_count = label_control.count()
            if lbl_count != 1:
                raise PageCreationError(
                    f"Expected exactly one toggle <label> in the Page Scroll "
                    f"Animation row, found {lbl_count}; refusing to click."
                )
            label_control.click()

        if not checkbox.is_checked():
            raise PageCreationError(
                "Could not enable 'Page Scroll Animation' (toggle still OFF "
                "after attempting to enable it)."
            )

    def _add_custom_section(self, data: SEOPage) -> None:
        """Add a Customizable section and fill headline/subheadline/description."""
        before = self._section_count()
        self.page.get_by_role("button", name="Add Section").first.click()
        self._click_section_category("content", "customizable_category")

        # Explicitly select the required layout. The builder defaults to
        # 'Hero Overlay'; the layout cards expose no role/test-id/aria, so we
        # match the card's exact label text. Verify a UNIQUE, visible match
        # BEFORE clicking — a missing (0) or ambiguous (>1) match raises rather
        # than silently keeping the default layout. (Locator confirmed live.)
        layout_label = S.get("content", "customizable_layout_split_right").value
        layout = self.page.get_by_text(layout_label, exact=True)
        try:
            layout.first.wait_for(state="visible", timeout=self.config.timeout_ms)
        except PlaywrightTimeoutError as exc:
            raise PageCreationError(
                f"Custom-section layout {layout_label!r} not found; refusing to "
                f"continue with the default layout."
            ) from exc
        count = layout.count()
        if count != 1:
            raise PageCreationError(
                f"Custom-section layout {layout_label!r} did not match uniquely "
                f"(matched {count}); refusing to continue with the default "
                f"layout."
            )
        layout.click()

        hl = self.page.get_by_placeholder(
            S.get("content", "customizable_headline").value
        )
        hl.first.wait_for(state="visible", timeout=self.config.timeout_ms)
        hl.first.fill(data.title)
        self.page.get_by_placeholder(
            S.get("content", "customizable_subheadline").value
        ).first.fill(data.subtitle)
        self.page.get_by_placeholder(
            S.get("content", "customizable_description").value
        ).first.fill(data.description)

        # Enable 'Page Scroll Animation' (Typography & Animation) before saving.
        self._enable_scroll_animation()

        self.page.get_by_role(
            "button",
            name=_role_button_name(S.get("content", "customizable_save").value),
        ).first.click()
        self.page.wait_for_url(
            re.compile(r".*/admin/page-settings.*page_id=.*"),
            timeout=self.config.timeout_ms,
        )
        self._wait_section_added(before)

    def _add_faq_section(self, data: SEOPage) -> None:
        """Add a FAQ section and every question/answer pair."""
        before = self._section_count()
        self.page.get_by_role("button", name="Add Section").first.click()
        self._click_section_category("faq", "faq_category")

        add_name = _role_button_name(S.get("faq", "add_faq_item_button").value)
        q_ph = S.get("faq", "faq_question_field").value
        a_ph = S.get("faq", "faq_answer_field").value

        add_btn = self.page.get_by_role("button", name=add_name)
        add_btn.first.wait_for(state="visible", timeout=self.config.timeout_ms)

        for i, faq in enumerate(data.faqs):
            add_btn.first.click()
            self.page.get_by_placeholder(q_ph).nth(i).wait_for(
                state="visible", timeout=self.config.timeout_ms
            )
            self.page.get_by_placeholder(q_ph).nth(i).fill(faq.question)
            self.page.get_by_placeholder(a_ph).nth(i).fill(faq.answer)

        if (
            self.page.get_by_placeholder(q_ph).count() != len(data.faqs)
            or self.page.get_by_placeholder(a_ph).count() != len(data.faqs)
        ):
            raise PageCreationError("FAQ field count mismatch before save")

        self.page.get_by_role(
            "button", name=_role_button_name(S.get("faq", "faq_save").value)
        ).first.click()
        self.page.wait_for_url(
            re.compile(r".*/admin/page-settings.*page_id=.*"),
            timeout=self.config.timeout_ms,
        )
        self._wait_section_added(before)

    def _publish_page(self) -> None:
        """Publish the current page (only called when publish=True)."""
        self.page.get_by_role(
            "button", name=_role_button_name(S.get("finalization", "publish_button").value)
        ).first.click()
        self.page.wait_for_timeout(1500)

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


def _role_button_name(role_value: str) -> str:
    """Extract ``X`` from a registry value like ``button[name="X"]``.

    Falls back to the raw value if no ``name="..."`` is present.
    """
    match = re.search(r'name="([^"]+)"', role_value or "")
    return match.group(1) if match else (role_value or "")


def _normalize_slug(href: str) -> str:
    """Normalize an href to a leading-slash slug for exact row matching."""
    s = (href or "").strip()
    if s and not s.startswith("/"):
        s = "/" + s
    return s
