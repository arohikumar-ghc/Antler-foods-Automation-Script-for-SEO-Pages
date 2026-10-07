"""Unit tests for the local structured-document parser (Step 6)."""
import pytest

from antler_seo.input.local_document import parse_text


SINGLE = """\
=== PAGE START ===
Page Name: Butter Chicken
Href: butter-chicken
SEO Title: Order Butter Chicken
SEO Description: Creamy butter chicken.
Subtitle: Authentic Indian
Title: Butter Chicken
Description: Our signature dish.
FAQ Question 1: Is it spicy?
FAQ Answer 1: Mild to medium.
=== PAGE END ===
"""


def test_single_page():
    outcome = parse_text(SINGLE)
    assert len(outcome.pages) == 1
    assert not outcome.has_errors
    page = outcome.pages[0]
    assert page.page_name == "Butter Chicken"
    assert page.href == "/butter-chicken"  # normalized
    assert len(page.faqs) == 1


def test_multiple_faqs_ordered():
    text = """\
=== PAGE START ===
Page Name: Naan
Href: /naan
SEO Title: Naan
SEO Description: Bread.
Subtitle: Breads
Title: Naan
Description: Fresh naan.
FAQ Question 2: Second?
FAQ Answer 2: B.
FAQ Question 1: First?
FAQ Answer 1: A.
FAQ Question 3: Third?
FAQ Answer 3: C.
=== PAGE END ===
"""
    outcome = parse_text(text)
    page = outcome.pages[0]
    assert [f.question for f in page.faqs] == ["First?", "Second?", "Third?"]


def test_optional_social_fields_present():
    text = """\
=== PAGE START ===
Page Name: Paneer
Href: /paneer
SEO Title: Paneer
SEO Description: Cheese.
Social Title: Social Paneer
Social Description: Social desc.
Subtitle: Veg
Title: Paneer
Description: Grilled cheese.
FAQ Question 1: Q?
FAQ Answer 1: A.
=== PAGE END ===
"""
    page = parse_text(text).pages[0]
    assert page.social_title == "Social Paneer"
    assert page.social_description == "Social desc."
    assert not page.social_title_is_fallback()


def test_optional_social_fields_absent_default_none():
    page = parse_text(SINGLE).pages[0]
    assert page.social_title is None
    assert page.social_description is None
    assert page.social_title_is_fallback()


def test_optional_image_captured_but_not_processed():
    text = """\
=== PAGE START ===
Page Name: Img
Href: /img
SEO Title: Img
SEO Description: Desc.
Image: 001-hero.jpg
Subtitle: Sub
Title: Title
Description: Body.
FAQ Question 1: Q?
FAQ Answer 1: A.
=== PAGE END ===
"""
    page = parse_text(text).pages[0]
    assert page.image is not None
    assert page.image.filename == "001-hero.jpg"
    assert page.image.local_path is None  # not processed


def test_image_absent_is_none():
    page = parse_text(SINGLE).pages[0]
    assert page.image is None


def test_multiline_description_with_colon_url():
    text = """\
=== PAGE START ===
Page Name: Multi
Href: /multi
SEO Title: Multi
SEO Description: Desc.
Subtitle: Sub
Title: Title
Description: First line of body.
See https://example.com/path for more.
Still part of the description.
FAQ Question 1: Q?
FAQ Answer 1: A.
=== PAGE END ===
"""
    page = parse_text(text).pages[0]
    assert "https://example.com/path" in page.description
    assert "Still part of the description." in page.description


def test_missing_required_field_is_isolated():
    text = """\
=== PAGE START ===
Page Name: Bad
Href: /bad
SEO Title: Bad
=== PAGE END ===
"""
    outcome = parse_text(text)
    assert outcome.pages == []
    assert len(outcome.errors) == 1
    assert outcome.errors[0].index == 1
    assert "missing required fields" in outcome.errors[0].message


def test_missing_faq_is_error():
    text = """\
=== PAGE START ===
Page Name: NoFaq
Href: /nofaq
SEO Title: NoFaq
SEO Description: Desc.
Subtitle: Sub
Title: Title
Description: Body.
=== PAGE END ===
"""
    outcome = parse_text(text)
    assert outcome.pages == []
    assert "FAQ" in outcome.errors[0].message


def test_incomplete_faq_pair_dropped():
    # Question without matching answer -> no usable FAQ -> error.
    text = """\
=== PAGE START ===
Page Name: Half
Href: /half
SEO Title: Half
SEO Description: Desc.
Subtitle: Sub
Title: Title
Description: Body.
FAQ Question 1: Only a question?
=== PAGE END ===
"""
    outcome = parse_text(text)
    assert outcome.pages == []
    assert outcome.errors


def test_malformed_page_does_not_corrupt_valid_pages():
    text = """\
=== PAGE START ===
Page Name: Good One
Href: /good-one
SEO Title: Good
SEO Description: Desc.
Subtitle: Sub
Title: Title
Description: Body.
FAQ Question 1: Q?
FAQ Answer 1: A.
=== PAGE END ===

=== PAGE START ===
Page Name: Broken
Href: /broken
SEO Title: Broken
=== PAGE END ===

=== PAGE START ===
Page Name: Good Two
Href: /good-two
SEO Title: Good2
SEO Description: Desc2.
Subtitle: Sub
Title: Title2
Description: Body2.
FAQ Question 1: Q2?
FAQ Answer 1: A2.
=== PAGE END ===
"""
    outcome = parse_text(text)
    assert [p.page_name for p in outcome.pages] == ["Good One", "Good Two"]
    assert len(outcome.errors) == 1
    assert outcome.errors[0].index == 2


def test_no_delimiters_yields_nothing():
    outcome = parse_text("No delimiters here.\nPage Name: x\n")
    assert outcome.pages == []
    assert outcome.errors == []


def test_case_insensitive_labels():
    text = """\
=== PAGE START ===
page name: Lower
HREF: /lower
seo title: Lower
Seo Description: Desc.
SUBTITLE: Sub
title: Title
DESCRIPTION: Body.
faq question 1: Q?
faq answer 1: A.
=== PAGE END ===
"""
    page = parse_text(text).pages[0]
    assert page.page_name == "Lower"
    assert page.href == "/lower"
    assert len(page.faqs) == 1


def test_missing_page_end_still_parses_fields():
    # No closing delimiter; required fields still present.
    text = """\
=== PAGE START ===
Page Name: Unterminated
Href: /unterminated
SEO Title: U
SEO Description: Desc.
Subtitle: Sub
Title: Title
Description: Body.
FAQ Question 1: Q?
FAQ Answer 1: A.
"""
    outcome = parse_text(text)
    assert len(outcome.pages) == 1
    assert outcome.pages[0].page_name == "Unterminated"
