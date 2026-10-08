"""Unit tests for pure helpers in antler_cms (no browser) — Step 11."""
import pytest

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


def test_no_hardcoded_restaurant_in_module():
    # Guard the architectural rule: 'Renovo' must never be hard-coded.
    import inspect
    import antler_seo.automation.antler_cms as mod

    src = inspect.getsource(mod)
    assert "Renovo" not in src
