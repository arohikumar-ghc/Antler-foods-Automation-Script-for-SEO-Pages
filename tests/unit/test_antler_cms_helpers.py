"""Unit tests for pure helpers in antler_cms (no browser) — Step 11."""
import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from antler_seo.automation.antler_cms import (
    AntlerCMS,
    RestaurantSelectionError,
    _origin_of,
    _restaurant_id_from_url,
)
from antler_seo.config import Config


def _config():
    return Config(
        email="user@example.com",
        password="secret",
        base_url="https://app.tryantler.com/login",
        headless=True,
    )


def test_origin_strips_path():
    assert _origin_of("https://app.tryantler.com/login") == "https://app.tryantler.com"
    assert _origin_of("https://app.tryantler.com") == "https://app.tryantler.com"
    assert _origin_of("http://host:8080/x/y") == "http://host:8080"


def test_origin_invalid_raises():
    with pytest.raises(ValueError):
        _origin_of("not-a-url")


def test_restaurant_id_extraction():
    url = (
        "https://app.tryantler.com/dashboard/admin/home"
        "?restaurant_id=abc-123&restaurant_name=Renovo"
    )
    assert _restaurant_id_from_url(url) == "abc-123"


def test_restaurant_id_absent_returns_none():
    assert _restaurant_id_from_url("https://app.tryantler.com/dashboard") is None


def test_cms_uses_origin_not_full_base_url():
    cms = AntlerCMS(page=None, config=_config())
    # base_url included /login; origin must drop it.
    assert cms._origin == "https://app.tryantler.com"


def test_pages_url_is_tenant_scoped():
    cms = AntlerCMS(page=None, config=_config())
    cms.restaurant_id = "rid-9"
    cms.restaurant_name = "Taste & Best"
    url = cms._pages_url()
    assert url.startswith(
        "https://app.tryantler.com/dashboard/admin/website/pages-settings?"
    )
    assert "restaurant_id=rid-9" in url
    # Name is URL-encoded (space + ampersand).
    assert "restaurant_name=Taste%20%26%20Best" in url


def test_select_restaurant_rejects_empty_name():
    cms = AntlerCMS(page=None, config=_config())
    with pytest.raises(RestaurantSelectionError):
        cms.select_restaurant("   ")


def test_open_pages_requires_selection():
    from antler_seo.automation.antler_cms import NavigationError

    cms = AntlerCMS(page=None, config=_config())
    with pytest.raises(NavigationError):
        cms.open_pages()


# --- Page Scroll Animation toggle (offline, fake page) ---------------------


class _FakeCheckbox:
    def __init__(self, checked, count=1):
        self._checked = checked
        self._count = count

    def count(self):
        return self._count

    def is_checked(self):
        return self._checked


class _FakeLabel:
    """Row <label>: clicking it turns the associated checkbox ON."""

    def __init__(self, checkbox, count=1):
        self._cb = checkbox
        self._count = count
        self.clicks = 0

    def count(self):
        return self._count

    def click(self, **kw):
        self.clicks += 1
        self._cb._checked = True


class _FakeRow:
    def __init__(self, checkbox, label):
        self._cb = checkbox
        self._label = label

    def locator(self, sel):
        # row.locator(input[...]) -> checkbox; row.locator('label') -> label
        if "input" in sel:
            return self._cb
        if sel == "label":
            return self._label
        return self


class _FakeHeading:
    def __init__(self, heading_count, row):
        self._count = heading_count
        self._row = row

    def count(self):
        return self._count

    def wait_for(self, **kw):
        # Only reached when count == 1 (caller checks uniqueness first).
        if self._count == 0:
            raise PlaywrightTimeoutError("heading not visible")

    def locator(self, sel):
        # heading.locator('xpath=ancestor::...') -> the row
        return self._row


class _FakePage:
    def __init__(self, heading_count=1, checked=False,
                 checkbox_count=1, label_count=1):
        self._cb = _FakeCheckbox(checked, checkbox_count)
        self._label = _FakeLabel(self._cb, label_count)
        self._row = _FakeRow(self._cb, self._label)
        self._heading = _FakeHeading(heading_count, self._row)

    def get_by_text(self, text, exact=False):
        return self._heading


def _cms_with(page):
    return AntlerCMS(page=page, config=_config())


def test_scroll_animation_enables_when_off():
    page = _FakePage(heading_count=1, checked=False)
    cms = _cms_with(page)
    cms._enable_scroll_animation()
    assert page._cb.is_checked() is True
    assert page._label.clicks == 1  # clicked exactly once to turn ON


def test_scroll_animation_leaves_already_on_untouched():
    page = _FakePage(heading_count=1, checked=True)
    cms = _cms_with(page)
    cms._enable_scroll_animation()
    assert page._cb.is_checked() is True
    assert page._label.clicks == 0  # never clicked an already-ON toggle


def test_scroll_animation_missing_raises():
    from antler_seo.automation.antler_cms import PageCreationError

    page = _FakePage(heading_count=0, checked=False)
    with pytest.raises(PageCreationError):
        _cms_with(page)._enable_scroll_animation()


def test_scroll_animation_ambiguous_raises():
    from antler_seo.automation.antler_cms import PageCreationError

    page = _FakePage(heading_count=2, checked=False)
    with pytest.raises(PageCreationError):
        _cms_with(page)._enable_scroll_animation()


def test_no_hardcoded_restaurant_in_module():
    # Guard the architectural rule: 'Renovo' must never be hard-coded.
    import inspect
    import antler_seo.automation.antler_cms as mod

    src = inspect.getsource(mod)
    assert "Renovo" not in src
