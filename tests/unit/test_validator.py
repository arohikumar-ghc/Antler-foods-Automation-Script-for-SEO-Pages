"""Unit tests for the validation layer (Step 7)."""
import pytest

from antler_seo.models import FAQ, ImageRef, SEOPage
from antler_seo.validation.validator import validate_pages


def _page(**overrides):
    data = dict(
        href="/butter-chicken",
        page_name="Butter Chicken",
        seo_title="Order Butter Chicken",
        seo_description="Creamy butter chicken.",
        subtitle="Authentic Indian",
        title="Butter Chicken",
        description="Our signature dish.",
        faqs=[FAQ("Is it spicy?", "Mild.")],
    )
    data.update(overrides)
    return SEOPage(**data)


def test_valid_single_page():
    report = validate_pages([_page()])
    assert report.passed
    assert report.total_errors() == 0
    assert report.valid_pages == [1]


def test_valid_multi_page():
    pages = [
        _page(href="/a", page_name="A"),
        _page(href="/b", page_name="B"),
        _page(href="/c", page_name="C"),
    ]
    report = validate_pages(pages)
    assert report.passed
    assert report.valid_pages == [1, 2, 3]


def test_empty_batch_fails():
    report = validate_pages([])
    assert not report.passed
    assert any("No pages" in e for e in report.errors)


def test_missing_required_field_fails_that_page_only():
    good = _page(href="/good", page_name="Good")
    bad = _page(href="/bad", page_name="Bad", seo_title="  ")
    report = validate_pages([good, bad])
    assert not report.passed
    assert report.pages[0].passed
    assert not report.pages[1].passed
    assert report.valid_pages == [1]


@pytest.mark.parametrize(
    "bad_href,reason",
    [
        ("/Has-Caps", "lowercase"),
        ("/has space", "spaces"),
        ("/bad_under", "slug"),
        ("/trailing/", "slug"),
    ],
)
def test_invalid_href_format(bad_href, reason):
    # Build directly to bypass model normalization niceties where needed.
    page = _page(href=bad_href, page_name="X")
    report = validate_pages([page])
    assert not report.passed
    assert any(reason in e for e in report.pages[0].errors)


def test_duplicate_href_detected():
    pages = [
        _page(href="/samosa", page_name="First"),
        _page(href="samosa", page_name="Second"),  # normalizes to /samosa
    ]
    report = validate_pages(pages)
    assert not report.passed
    assert any("duplicate href" in e for e in report.pages[1].errors)
    # First occurrence remains valid.
    assert report.pages[0].passed


def test_page_count_match_no_warning():
    report = validate_pages([_page()], expected_page_count=1)
    assert report.passed
    assert report.total_warnings() == 0


def test_page_count_mismatch_warns_but_passes():
    report = validate_pages([_page()], expected_page_count=3)
    assert report.passed  # warning, not error
    assert any("page count mismatch" in w for w in report.warnings)


# --- image validation gating ----------------------------------------------


def test_image_validation_disabled_by_default():
    # Page has an image that does not exist, but images are disabled -> no error.
    page = _page(image=ImageRef(filename="missing.jpg"))
    report = validate_pages([page])
    assert report.passed
    assert report.total_errors() == 0


def test_image_validation_enabled_missing_dir():
    page = _page(image=ImageRef(filename="missing.jpg"))
    report = validate_pages([page], images_enabled=True)
    assert not report.passed
    assert any("no image directory" in e for e in report.pages[0].errors)


def test_image_validation_enabled_file_missing(tmp_path):
    page = _page(image=ImageRef(filename="missing.jpg"))
    report = validate_pages(
        [page], images_enabled=True, image_dir=str(tmp_path)
    )
    assert not report.passed
    assert any("image file not found" in e for e in report.pages[0].errors)


def test_image_validation_enabled_file_present(tmp_path):
    img = tmp_path / "hero.jpg"
    img.write_bytes(b"fake")
    page = _page(image=ImageRef(filename="hero.jpg"))
    report = validate_pages(
        [page], images_enabled=True, image_dir=str(tmp_path)
    )
    assert report.passed


def test_image_enabled_but_no_image_on_page_is_fine():
    report = validate_pages([_page()], images_enabled=True)
    assert report.passed
