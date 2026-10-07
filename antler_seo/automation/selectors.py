"""
Central selector registry for the Antler CMS — SCAFFOLD ONLY.

This is the single place where Antler UI selectors will live, so a UI change
touches one file. It is intentionally **not populated**: no selectors are
invented or guessed here. Real, verified values are added during
**Phase 4 → Step 10 — Antler UI Investigation**, captured against the live
Antler interface.

Structure
---------
``Selector`` pairs an unresolved placeholder with the metadata needed to fill it
in later. ``SELECTORS`` groups them by UI area so the investigation has a clear
checklist to complete. ``is_fully_populated()`` reports whether every selector
has been given a real value — the automation layer can assert on this before it
runs, guaranteeing we never ship empty placeholders.

Nothing in this module imports Playwright or touches a browser.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class Selector:
    """A single UI selector placeholder, to be resolved during investigation.

    Attributes:
        name: Stable logical key used by the automation code.
        description: What the element is / how to recognise it in the UI.
        strategy: Intended Playwright strategy once known (e.g. "role",
            "label", "text", "css"). Left as a hint only.
        value: The actual selector string. ``None`` until investigated.
    """

    name: str
    description: str
    strategy: Optional[str] = None
    value: Optional[str] = None

    @property
    def is_resolved(self) -> bool:
        return bool(self.value)


def _ph(name: str, description: str) -> Selector:
    """Create an unresolved placeholder selector."""
    return Selector(name=name, description=description, strategy=None, value=None)


# Grouped by UI area. Mirrors the Phase 4 Antler UI Investigation checklist.
# Every value is None by design and must be filled in during Step 10.
SELECTORS: Dict[str, Dict[str, Selector]] = {
    "auth": {
        "login_url_path": _ph(
            "login_url_path", "Path appended to base_url to reach the login page"
        ),
        "email_field": _ph("email_field", "Login email input"),
        "password_field": _ph("password_field", "Login password input"),
        "login_button": _ph("login_button", "Submit/login button"),
        "login_success_indicator": _ph(
            "login_success_indicator", "Element proving login succeeded"
        ),
        "login_error_indicator": _ph(
            "login_error_indicator", "Element shown on invalid credentials"
        ),
    },
    "navigation": {
        "dashboard_indicator": _ph(
            "dashboard_indicator", "Landmark confirming the dashboard loaded"
        ),
        "tenant_selector": _ph(
            "tenant_selector", "Site/tenant selector (if Antler is multi-tenant)"
        ),
        "page_management_entry": _ph(
            "page_management_entry", "Entry point to SEO/page management"
        ),
        "editor_ready_indicator": _ph(
            "editor_ready_indicator", "Element confirming the editor is ready"
        ),
    },
    "page": {
        "existing_page_item": _ph(
            "existing_page_item", "How an existing page appears in the list"
        ),
        "add_page_button": _ph("add_page_button", "Control to create a new page"),
        "href_field": _ph("href_field", "Page href/slug input"),
        "page_name_field": _ph("page_name_field", "Page name input"),
        "save_button": _ph("save_button", "Save control for the page shell"),
        "edit_button": _ph("edit_button", "Control to enter edit mode"),
    },
    "seo": {
        "seo_title_field": _ph("seo_title_field", "SEO title input"),
        "seo_description_field": _ph(
            "seo_description_field", "SEO meta description input"
        ),
        "seo_save_button": _ph("seo_save_button", "Save control for SEO fields"),
    },
    "social": {
        "social_title_field": _ph("social_title_field", "Social title input"),
        "social_description_field": _ph(
            "social_description_field", "Social description input"
        ),
        "social_save_button": _ph(
            "social_save_button", "Save control for social fields"
        ),
    },
    "content": {
        "add_content_control": _ph(
            "add_content_control", "Control to add a content/body block"
        ),
        "subtitle_field": _ph("subtitle_field", "Content subtitle input"),
        "heading_field": _ph("heading_field", "Content heading/title input"),
        "body_field": _ph("body_field", "Content body/description input"),
        "content_save_button": _ph(
            "content_save_button", "Save control for the content block"
        ),
    },
    "faq": {
        "add_faq_section_control": _ph(
            "add_faq_section_control", "Control to add a FAQ section/block"
        ),
        "add_faq_item_button": _ph(
            "add_faq_item_button", "Control to add a single FAQ item"
        ),
        "faq_question_field": _ph("faq_question_field", "FAQ question input"),
        "faq_answer_field": _ph("faq_answer_field", "FAQ answer input"),
        "faq_item_save_button": _ph(
            "faq_item_save_button", "Save control for a FAQ item"
        ),
    },
    "finalization": {
        "publish_button": _ph(
            "publish_button", "Explicit publish/submit control (if one exists)"
        ),
        "success_indicator": _ph(
            "success_indicator", "Overall success/confirmation indicator"
        ),
    },
}


def get(group: str, name: str) -> Selector:
    """Return a selector by group and name.

    Raises:
        KeyError: If the group or name is unknown.
    """
    return SELECTORS[group][name]


def all_selectors() -> List[Selector]:
    """Return a flat list of every selector in the registry."""
    return [sel for group in SELECTORS.values() for sel in group.values()]


def unresolved() -> List[Selector]:
    """Return selectors that still need real values (all of them, for now)."""
    return [sel for sel in all_selectors() if not sel.is_resolved]


def is_fully_populated() -> bool:
    """True only when every selector has a real value (post-investigation)."""
    return not unresolved()
