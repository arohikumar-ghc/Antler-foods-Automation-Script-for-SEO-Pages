"""Unit tests for restaurant/tenant context carried from the input (Step 11)."""
from antler_seo.input.base import ParseOutcome
from antler_seo.input.local_document import parse_text, LocalDocumentSource


DOC_WITH_HEADER = """\
Restaurant: Renovo

=== PAGE START ===
Page Name: About
Href: /about
SEO Title: About
SEO Description: About us.
Subtitle: Sub
Title: Title
Description: Body.
FAQ Question 1: Q?
FAQ Answer 1: A.
=== PAGE END ===
"""

DOC_WITHOUT_HEADER = """\
=== PAGE START ===
Page Name: About
Href: /about
SEO Title: About
SEO Description: About us.
Subtitle: Sub
Title: Title
Description: Body.
FAQ Question 1: Q?
FAQ Answer 1: A.
=== PAGE END ===
"""


def test_parse_outcome_defaults_restaurant_none():
    outcome = ParseOutcome()
    assert outcome.restaurant_name is None
    assert not outcome.has_restaurant


def test_restaurant_header_parsed():
    outcome = parse_text(DOC_WITH_HEADER)
    assert outcome.restaurant_name == "Renovo"
    assert outcome.has_restaurant
    assert len(outcome.pages) == 1


def test_no_restaurant_header_is_none():
    outcome = parse_text(DOC_WITHOUT_HEADER)
    assert outcome.restaurant_name is None
    assert not outcome.has_restaurant
    # Pages still parse fine without the header.
    assert len(outcome.pages) == 1


def test_restaurant_header_only_read_from_preamble():
    # A 'Restaurant:' line inside a page body must NOT become the document
    # restaurant (it would just be an unknown field, ignored).
    doc = DOC_WITHOUT_HEADER.replace(
        "Subtitle: Sub", "Restaurant: NotTheTenant\nSubtitle: Sub"
    )
    outcome = parse_text(doc)
    assert outcome.restaurant_name is None


def test_source_override_takes_precedence(tmp_path):
    f = tmp_path / "doc.md"
    f.write_text(DOC_WITH_HEADER, encoding="utf-8")
    outcome = LocalDocumentSource(str(f), restaurant_name="Overridden").load()
    assert outcome.restaurant_name == "Overridden"


def test_source_without_override_uses_header(tmp_path):
    f = tmp_path / "doc.md"
    f.write_text(DOC_WITH_HEADER, encoding="utf-8")
    outcome = LocalDocumentSource(str(f)).load()
    assert outcome.restaurant_name == "Renovo"


def test_restaurant_name_not_on_seopage():
    # Restaurant context must live at the batch level, not per page.
    outcome = parse_text(DOC_WITH_HEADER)
    assert not hasattr(outcome.pages[0], "restaurant_name")
