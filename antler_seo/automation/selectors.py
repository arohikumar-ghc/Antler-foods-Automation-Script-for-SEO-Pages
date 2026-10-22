"""
Central selector registry for the Antler CMS.

Populated during Phase 4 → Step 10 (Antler UI Investigation) from the REAL
Antler CMS (app.tryantler.com), using the Renovo restaurant. Evidence sources:

  * live read-only inspection of the DOM (stable ``id`` attributes, roles,
    placeholders), and
  * a Playwright codegen recording of the end-to-end flow.

Every entry records a primary ``value``, the ``strategy``, an optional
``fallback``, whether it was ``verified`` against the live UI, and whether it is
``needs_cleanup`` (fragile — must be replaced with a stable selector before
production use). See ``docs/antler_ui_investigation.md`` for full context.

NO credentials live here. Credentials come only from ``.env`` via Config.
This module does not import Playwright or touch a browser. It is data only;
``antler_cms.py`` (Steps 11–16) will consume these values.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class Selector:
    """A single UI selector discovered during investigation.

    Attributes:
        name: Stable logical key used by the automation code.
        description: What the element is / where it lives in the UI.
        strategy: How ``value`` should be used — one of "css", "role", "label",
            "placeholder", "text", "title", "url", "path".
        value: The primary selector string, or ``None`` if not yet discovered.
        fallback: An alternate selector string (used if the primary fails).
        verified: True if confirmed against the live Antler UI.
        needs_cleanup: True if the selector is fragile (positional / volatile
            accessible name) and should be replaced before production use.
    """

    name: str
    description: str
    strategy: Optional[str] = None
    value: Optional[str] = None
    fallback: Optional[str] = None
    verified: bool = False
    needs_cleanup: bool = False

    @property
    def is_resolved(self) -> bool:
        return bool(self.value)


def _sel(name, description, strategy, value, *, fallback=None,
         verified=True, needs_cleanup=False) -> Selector:
    return Selector(
        name=name, description=description, strategy=strategy, value=value,
        fallback=fallback, verified=verified, needs_cleanup=needs_cleanup,
    )


def _ph(name: str, description: str) -> Selector:
    """An intentionally-unresolved entry (element absent or not yet captured)."""
    return Selector(name=name, description=description)


# Grouped by UI area. Values are REAL selectors from the Antler CMS unless the
# entry is a documented placeholder (value=None).
SELECTORS: Dict[str, Dict[str, Selector]] = {
    "auth": {
        "login_url_path": _sel(
            "login_url_path", "Path for the login page (appended to origin)",
            "path", "/login"),
        "email_field": _sel(
            "email_field", "Login email input",
            "css", "#email-address",
            fallback='role=textbox[name="Email Address"]'),
        "password_field": _sel(
            "password_field", "Login password input",
            "css", "#password",
            fallback='role=textbox[name="Password"]'),
        "login_button": _sel(
            "login_button", "Sign In submit button",
            "role", 'button[name="Sign In"]'),
        "turnstile_iframe": _sel(
            "turnstile_iframe",
            "Cloudflare Turnstile challenge iframe on the login page. Usually "
            "auto-passes in managed mode; the recording clicked its body.",
            "css", "iframe[src*='challenges.cloudflare.com']",
            verified=True, needs_cleanup=True),
        "login_success_indicator": _sel(
            "login_success_indicator",
            "After login the URL leaves /login and lands on the admin dashboard",
            "url", "/dashboard/admin/home"),
        "login_error_indicator": _ph(
            "login_error_indicator",
            "Wrong-credential error state — NOT captured (never submitted bad "
            "credentials). Must be investigated before relying on it."),
    },
    "navigation": {
        # Antler is MULTI-TENANT: a restaurant must be selected first.
        "restaurant_search": _sel(
            "restaurant_search", "Restaurant/tenant search box (top of app)",
            "placeholder", "Search restaurant..."),
        "restaurant_option": _sel(
            "restaurant_option",
            "Restaurant suggestion button; name is the restaurant (e.g. Renovo)",
            "role", 'button[name="{restaurant_name}"][exact]'),
        "clear_restaurant": _sel(
            "clear_restaurant", "Clears the selected restaurant",
            "role", 'button[name="Clear selected restaurant"]'),
        "website_nav": _sel(
            "website_nav", "Sidebar WEBSITE section toggle",
            "role", 'button[name="Website"]'),
        "pages_link": _sel(
            "pages_link", "WEBSITE > Pages link (page management)",
            "role", 'link[name="Pages"]',
            fallback="a[href*='/dashboard/admin/website/pages-settings']"),
        "editor_ready_indicator": _sel(
            "editor_ready_indicator",
            "Page editor is ready when the Add Section control is present",
            "role", 'button[name="Add Section"]'),
    },
    "page": {
        "pages_table": _sel(
            "pages_table", "Table listing all pages (PAGE, URL SLUG, STATUS, "
            "VISIBILITY, UPDATED, ACTIONS)",
            "css", "table tbody tr"),
        "create_page_button": _sel(
            "create_page_button", "Opens the Create Page modal",
            "role", 'button[name="Create Page"]'),
        "create_modal_name": _sel(
            "create_modal_name", "Create modal: Page Name field",
            "css", "#name",
            fallback='role=textbox[name="Page Name*"]'),
        "create_modal_slug": _sel(
            "create_modal_slug",
            "Create modal: URL Slug field (auto-generated from name if blank)",
            "css", "#url_slug"),
        "create_modal_meta_title": _sel(
            "create_modal_meta_title", "Create modal: Meta Title (SEO title)",
            "css", "#meta_title",
            fallback='role=textbox[name="Meta Title(0/60)"]'),
        "create_modal_meta_description": _sel(
            "create_modal_meta_description",
            "Create modal: Meta Description (SEO description)",
            "css", "#meta_description",
            fallback='role=textbox[name="Meta Description(0/160)"]'),
        "create_modal_keywords": _sel(
            "create_modal_keywords", "Create modal: Keywords (optional)",
            "css", "#keywords"),
        "create_modal_published": _sel(
            "create_modal_published", "Create modal: Published checkbox",
            "css", "#modal_published"),
        "create_modal_show_navbar": _sel(
            "create_modal_show_navbar", "Create modal: Show in Navbar checkbox",
            "css", "#modal_show_on_navbar"),
        "create_modal_show_footer": _sel(
            "create_modal_show_footer", "Create modal: Show in Footer checkbox",
            "css", "#modal_show_on_footer"),
        "create_submit": _sel(
            "create_submit", "Create modal submit button (scoped to the form)",
            "css", "form >> role=button[name=\"Create Page\"]"),
        "row_edit_button": _sel(
            "row_edit_button", "Per-row Edit page button (scope to a row)",
            "css", "button[title='Edit page']",
            fallback='role=button[name="Edit page"]'),
        "row_delete_button": _sel(
            "row_delete_button",
            "Per-row Delete page button (user-created pages only; System pages "
            "have no delete)",
            "css", "button[title='Delete page']"),
        "delete_confirm_button": _sel(
            "delete_confirm_button", "Confirm button in the delete dialog",
            "role", 'button[name="Delete Page"]'),
        "editor_back_button": _sel(
            "editor_back_button", "Editor: Back to pages list",
            "role", 'button[name="Back"]'),
        # In the editor, Page Settings > Edit exposes these ids.
        "editor_page_name": _sel(
            "editor_page_name", "Editor Page Settings: Page Name input",
            "css", "#page-name-input"),
        "editor_page_slug": _sel(
            "editor_page_slug", "Editor Page Settings: URL Slug input",
            "css", "#page-slug-input"),
    },
    "seo": {
        # SEO metadata is set at creation time (create modal) AND editable via
        # the editor's SEO panel.
        "seo_panel_button": _sel(
            "seo_panel_button", "Editor header: opens the SEO panel",
            "role", 'button[name="SEO"]'),
        "seo_panel_meta_title": _sel(
            "seo_panel_meta_title", "SEO panel: Meta Title field",
            "placeholder", "Your page title for search engines"),
        "seo_panel_meta_description": _sel(
            "seo_panel_meta_description", "SEO panel: Meta Description field",
            "placeholder",
            "A brief description of your page content for search results"),
        "seo_panel_keywords": _sel(
            "seo_panel_keywords", "SEO panel: Meta Keywords field",
            "placeholder", "food, dining, delivery, catering, online ordering"),
    },
    "social": {
        # KEY FINDING: Antler has NO dedicated social title / social description
        # TEXT fields. Meta Title/Description double as the social preview. Only
        # an Open Graph / "Social Sharing Image" control exists.
        "social_title_field": _ph(
            "social_title_field",
            "NOT PRESENT in Antler. No dedicated social title text field; the "
            "Meta Title serves as the social preview title."),
        "social_description_field": _ph(
            "social_description_field",
            "NOT PRESENT in Antler. No dedicated social description text field; "
            "the Meta Description serves as the social preview description."),
        "social_image_gallery_button": _sel(
            "social_image_gallery_button",
            "Open Graph / Social Sharing Image chooser (image handling DEFERRED "
            "to a later phase)",
            "role", 'button[name="Choose Image from Gallery"]',
            verified=True),
    },
    "content": {
        # 'Customizable' section maps to our body content.
        "add_first_section_button": _sel(
            "add_first_section_button",
            "Empty-state button when a page has no sections yet",
            "role", 'button[name="Add Your First Section"]'),
        "add_section_button": _sel(
            "add_section_button",
            "Opens the section-type picker (when sections already exist)",
            "role", 'button[name="Add Section"]'),
        "customizable_category": _sel(
            "customizable_category",
            "Section picker: the 'Customizable' category (maps to body content)."
            " Recording used a fragile positional selector; prefer the category "
            "heading text.",
            "text", "Customizable",
            fallback="div:nth-child(2) > .mb-3 > .flex > .h-4",
            verified=True, needs_cleanup=True),
        "customizable_layout_split_right": _sel(
            "customizable_layout_split_right",
            "Customizable layout template 'Split Right Image' (subtitle "
            "'Content on left, image on right'). Verified live: the layout card "
            "exposes no role/test-id/aria attribute, so the card's exact label "
            "text is the only reliable handle and is unique (count 1). Selected "
            "explicitly because the builder otherwise keeps its default layout "
            "'Hero Overlay'.",
            "text", "Split Right Image",
            verified=True, needs_cleanup=False),
        "customizable_headline": _sel(
            "customizable_headline", "Customizable: Headline (maps to title)",
            "placeholder", "Enter headline"),
        "customizable_subheadline": _sel(
            "customizable_subheadline",
            "Customizable: Subheadline (maps to subtitle)",
            "placeholder", "Enter subheadline"),
        "customizable_description": _sel(
            "customizable_description",
            "Customizable: Description (maps to description)",
            "placeholder", "Enter description"),
        "typography_scroll_animation_label": _sel(
            "typography_scroll_animation_label",
            "Typography & Animation group: the 'Page Scroll Animation' row "
            "heading. Verified live: unique <h3> text (exact-leaf count 1); used "
            "to anchor the row, since the toggle's <input> is visually hidden "
            "(sr-only) and exposes no accessible name/role.",
            "text", "Page Scroll Animation",
            verified=True, needs_cleanup=False),
        "typography_scroll_animation_input": _sel(
            "typography_scroll_animation_input",
            "The Page Scroll Animation toggle's control: a native "
            "<input type=checkbox> (state = .checked; ON == checked). Verified "
            "live: no role=switch/aria-checked; scoped within the label row.",
            "css", "input[type='checkbox']",
            verified=True, needs_cleanup=False),
        "customizable_save": _sel(
            "customizable_save", "Saves the Customizable section",
            "role", 'button[name="Save Custom Section Settings"]'),
    },
    "faq": {
        "faq_category": _sel(
            "faq_category",
            "Section picker: the 'FAQ' category. Recording used a fragile "
            "positional selector; prefer the category heading text.",
            "text", "FAQ",
            fallback="div:nth-child(8) > .mb-3 > .flex > .h-4",
            verified=True, needs_cleanup=True),
        "add_faq_item_button": _sel(
            "add_faq_item_button", "Adds a new empty FAQ question/answer pair",
            "role", 'button[name="Add FAQ"]'),
        "faq_question_field": _sel(
            "faq_question_field",
            "FAQ item question input (use .nth(i) for multiple items)",
            "placeholder", "Enter your question here..."),
        "faq_answer_field": _sel(
            "faq_answer_field",
            "FAQ item answer textarea (use .nth(i) for multiple items)",
            "placeholder", "Enter the answer here..."),
        "faq_save": _sel(
            "faq_save", "Saves the FAQ section",
            "role", 'button[name="Create FAQ Section"]'),
    },
    "finalization": {
        # Antler saves per-section (each section/modal has its own save). There
        # is no single global save; Publish toggles draft/published.
        "publish_button": _sel(
            "publish_button",
            "Editor header Publish button; row actions show Publish/Unpublish",
            "role", 'button[name="Publish"]',
            verified=True),
        "section_drag_handle": _sel(
            "section_drag_handle", "Drag handle to reorder sections",
            "title", "Drag this section to reorder",
            verified=True, needs_cleanup=True),
        "success_indicator": _ph(
            "success_indicator",
            "Toast/notification confirming a save — NOT reliably captured yet. "
            "Must be investigated to implement post-save verification."),
    },
}


def get(group: str, name: str) -> Selector:
    """Return a selector by group and name (raises KeyError if unknown)."""
    return SELECTORS[group][name]


def all_selectors() -> List[Selector]:
    """Flat list of every selector in the registry."""
    return [sel for group in SELECTORS.values() for sel in group.values()]


def resolved() -> List[Selector]:
    """Selectors that have a real value."""
    return [s for s in all_selectors() if s.is_resolved]


def unresolved() -> List[Selector]:
    """Documented selectors still without a value (e.g. absent in Antler)."""
    return [s for s in all_selectors() if not s.is_resolved]


def fragile() -> List[Selector]:
    """Resolved selectors flagged as needing a stable replacement."""
    return [s for s in all_selectors() if s.needs_cleanup]


def is_fully_populated() -> bool:
    """True only when every selector has a value (some remain unknown now)."""
    return not unresolved()
