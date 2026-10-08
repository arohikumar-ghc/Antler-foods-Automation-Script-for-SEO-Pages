"""Unit tests for the selector registry (Step 10 — populated).

The registry now holds REAL, verified Antler selectors plus a few documented
placeholders for elements that are absent in Antler or not yet captured. These
tests assert structural invariants, not the automation behaviour.
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


def test_core_selectors_are_resolved():
    # A sample of selectors that MUST be populated from the investigation.
    must_be_resolved = [
        ("auth", "email_field"),
        ("auth", "password_field"),
        ("auth", "login_button"),
        ("navigation", "restaurant_search"),
        ("navigation", "pages_link"),
        ("page", "create_page_button"),
        ("page", "create_modal_name"),
        ("page", "create_modal_meta_title"),
        ("content", "customizable_headline"),
        ("faq", "faq_question_field"),
        ("faq", "faq_answer_field"),
    ]
    for group, name in must_be_resolved:
        sel = selectors.get(group, name)
        assert sel.is_resolved, f"{group}.{name} should be resolved"
        assert sel.verified


def test_every_selector_has_name_and_description():
    for sel in selectors.all_selectors():
        assert sel.name
        assert sel.description


def test_known_absent_fields_are_documented_placeholders():
    # Antler has no dedicated social title/description text fields.
    for name in ("social_title_field", "social_description_field"):
        sel = selectors.get("social", name)
        assert not sel.is_resolved
        assert "NOT PRESENT" in sel.description


def test_fragile_selectors_are_flagged():
    frag = selectors.fragile()
    frag_names = {s.name for s in frag}
    # Positional / volatile selectors discovered in the recording.
    assert "customizable_category" in frag_names
    assert "faq_category" in frag_names
    for sel in frag:
        assert sel.needs_cleanup


def test_resolved_and_unresolved_partition():
    total = len(selectors.all_selectors())
    assert len(selectors.resolved()) + len(selectors.unresolved()) == total
    # Investigation left a few genuine unknowns (e.g. error state, toast).
    assert len(selectors.unresolved()) >= 1
    assert len(selectors.resolved()) >= 20


def test_no_credentials_in_registry():
    # Defensive: the registry must never contain credential-like values.
    blob = " ".join(
        f"{s.value} {s.fallback} {s.description}" for s in selectors.all_selectors()
    ).lower()
    assert "admin@123" not in blob
    assert "adminantler" not in blob
    assert "password=" not in blob
