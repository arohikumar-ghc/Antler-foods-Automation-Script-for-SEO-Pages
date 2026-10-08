"""Live integration test for Step 11 against the real Antler CMS.

Gated: skips automatically unless real credentials are available in the
environment (loaded from .env). Proves login + DYNAMIC restaurant selection +
navigation to Pages. The restaurant name is supplied via ANTLER_TEST_RESTAURANT
(default "Renovo") — demonstrating that selection is parameter-driven, never
hard-coded in the automation.

Run explicitly with:  pytest -m live
"""
import os

import pytest

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover
    pass

from antler_seo.config import Config, ConfigError
from antler_seo.automation.browser import BrowserSession
from antler_seo.automation.antler_cms import AntlerCMS


def _config_or_skip() -> Config:
    try:
        return Config.from_env(load_env_file=True)
    except ConfigError as exc:
        pytest.skip(f"Antler credentials not configured; skipping live test: {exc}")


pytestmark = pytest.mark.live


def test_login_select_restaurant_open_pages(tmp_path):
    config = _config_or_skip()
    # Run headless for CI-style execution regardless of .env setting.
    config.headless = True

    restaurant = os.getenv("ANTLER_TEST_RESTAURANT", "Renovo")

    with BrowserSession(config, screenshots_dir=str(tmp_path)) as session:
        cms = AntlerCMS(session.page, config)

        cms.login()
        assert "/login" not in session.page.url

        rid = cms.select_restaurant(restaurant)
        assert rid, "restaurant_id should be captured from the URL"
        assert cms.restaurant_name == restaurant
        assert "restaurant_id=" in session.page.url

        cms.open_pages()
        assert "pages-settings" in session.page.url
        # Create Page control confirms the Pages screen is ready.
        assert (
            session.page.get_by_role("button", name="Create Page").first.is_visible()
        )
