"""Integration tests: fixture file -> parser -> model (Step 6)."""
from pathlib import Path

import pytest

from antler_seo.input.base import InputError
from antler_seo.input.local_document import LocalDocumentSource, parse_file

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_single_page_fixture():
    outcome = parse_file(str(FIXTURES / "single_page.md"))
    assert len(outcome.pages) == 1
    page = outcome.pages[0]
    assert page.href == "/butter-chicken"
    assert page.image is not None and page.image.filename == "001-butter-chicken.jpg"
    assert len(page.faqs) == 2
    # Preamble before the first delimiter is ignored.
    assert page.page_name == "Butter Chicken"
    # Description continuation captured the trailing URL line.
    assert "https://example.com/menu" in page.description


def test_multi_page_fixture():
    outcome = parse_file(str(FIXTURES / "multi_page.md"))
    assert [p.page_name for p in outcome.pages] == [
        "Butter Chicken",
        "Garlic Naan",
        "Paneer Tikka",
    ]
    # href normalized even when written without a leading slash.
    assert outcome.pages[1].href == "/garlic-naan"
    assert len(outcome.pages[1].faqs) == 3
    assert outcome.pages[2].social_title == "Paneer Tikka - Grilled Cottage Cheese"


def test_mixed_valid_and_malformed_fixture():
    outcome = parse_file(str(FIXTURES / "mixed_valid_and_malformed.md"))
    assert [p.page_name for p in outcome.pages] == [
        "Valid Page One",
        "Valid Page Two",
    ]
    # Two malformed blocks (indexes 2 and 3) recorded as errors.
    assert {e.index for e in outcome.errors} == {2, 3}


def test_source_load_interface():
    source = LocalDocumentSource(str(FIXTURES / "single_page.md"))
    outcome = source.load()
    assert outcome.has_pages


def test_missing_file_raises_input_error():
    with pytest.raises(InputError):
        parse_file(str(FIXTURES / "does_not_exist.md"))
