"""Unit tests for the selector registry scaffold (Step 9).

Confirms the registry is a structural scaffold with NO invented Antler
selectors — every value must be unresolved until the UI investigation.
"""
from antler_seo.automation import selectors


def test_registry_groups_present():
    expected_groups = {
        "auth",
        "navigation",
        "page",
        "seo",
        "social",
        "content",
        "faq",
        "finalization",
    }
    assert expected_groups.issubset(set(selectors.SELECTORS.keys()))


def test_all_selectors_unresolved_by_default():
    # Scaffold only: nothing should have a real value yet.
    assert not selectors.is_fully_populated()
    assert len(selectors.unresolved()) == len(selectors.all_selectors())
    for sel in selectors.all_selectors():
        assert sel.value is None
        assert not sel.is_resolved


def test_every_selector_has_name_and_description():
    for sel in selectors.all_selectors():
        assert sel.name
        assert sel.description


def test_get_returns_selector():
    sel = selectors.get("auth", "email_field")
    assert sel.name == "email_field"
    assert not sel.is_resolved


def test_resolved_flag_tracks_value():
    sel = selectors.Selector(name="x", description="d", value="#real")
    assert sel.is_resolved
