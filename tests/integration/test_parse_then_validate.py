"""Integration: fixture -> parser -> validator (Step 6 + Step 7 together)."""
from pathlib import Path

from antler_seo.input.local_document import parse_file
from antler_seo.validation.validator import validate_pages

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_multi_page_fixture_validates_clean():
    outcome = parse_file(str(FIXTURES / "multi_page.md"))
    report = validate_pages(outcome.pages)
    assert report.passed
    assert report.valid_pages == [1, 2, 3]


def test_duplicate_href_fixture_fails_validation():
    outcome = parse_file(str(FIXTURES / "duplicate_href.md"))
    assert len(outcome.pages) == 2  # both parse fine
    report = validate_pages(outcome.pages)
    assert not report.passed
    assert any("duplicate href" in e for e in report.pages[1].errors)


def test_mixed_fixture_parses_valid_and_validates_them():
    outcome = parse_file(str(FIXTURES / "mixed_valid_and_malformed.md"))
    # Parser already dropped malformed pages.
    assert len(outcome.pages) == 2
    assert len(outcome.errors) == 2
    # The surviving pages validate cleanly.
    report = validate_pages(outcome.pages)
    assert report.passed


def test_single_page_fixture_with_declared_count():
    outcome = parse_file(str(FIXTURES / "single_page.md"))
    report = validate_pages(outcome.pages, expected_page_count=1)
    assert report.passed
    assert report.total_warnings() == 0
