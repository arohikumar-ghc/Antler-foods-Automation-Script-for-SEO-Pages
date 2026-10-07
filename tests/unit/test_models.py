"""Unit tests for the data models (Step 5)."""
import pytest

from antler_seo.models import (
    FAQ,
    ImageRef,
    SEOPage,
    PageResult,
    BatchResult,
    normalize_href,
    STATUS_SUCCESS,
    STATUS_PARTIAL,
    STATUS_FAILED,
    STATUS_SKIPPED,
    SECTION_BASIC_INFO,
    SECTION_SEO_METADATA,
    SECTION_SOCIAL_METADATA,
    SECTION_CONTENT,
    SECTION_FAQ,
)


def _valid_page(**overrides):
    data = dict(
        href="/butter-chicken",
        page_name="Butter Chicken",
        seo_title="Order Butter Chicken",
        seo_description="Creamy butter chicken, order now.",
        subtitle="Authentic Indian",
        title="Butter Chicken",
        description="Our signature butter chicken.",
        faqs=[FAQ("Is it spicy?", "Mild to medium.")],
    )
    data.update(overrides)
    return SEOPage(**data)


# --- href normalization ----------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("butter-chicken", "/butter-chicken"),
        ("/butter-chicken", "/butter-chicken"),
        ("  butter-chicken  ", "/butter-chicken"),
        ("", ""),
        (None, ""),
    ],
)
def test_normalize_href(raw, expected):
    assert normalize_href(raw) == expected


def test_seopage_normalizes_href_on_init():
    page = _valid_page(href="paneer-tikka")
    assert page.href == "/paneer-tikka"


# --- FAQ -------------------------------------------------------------------


def test_faq_valid():
    assert FAQ("Q?", "A.").is_valid()


def test_faq_empty_question():
    errors = FAQ("", "A.").validate()
    assert any("question" in e for e in errors)


def test_faq_empty_answer():
    errors = FAQ("Q?", "   ").validate()
    assert any("answer" in e for e in errors)


# --- SEOPage validation ----------------------------------------------------


def test_valid_page():
    assert _valid_page().is_valid()


@pytest.mark.parametrize(
    "field_name",
    [
        "page_name",
        "seo_title",
        "seo_description",
        "subtitle",
        "title",
        "description",
    ],
)
def test_missing_required_text_field(field_name):
    page = _valid_page(**{field_name: "  "})
    errors = page.validate()
    assert any(field_name in e for e in errors)


def test_missing_href():
    page = _valid_page(href="")
    errors = page.validate()
    assert any("href" in e for e in errors)


def test_missing_faqs():
    page = _valid_page(faqs=[])
    errors = page.validate()
    assert any("FAQ" in e for e in errors)


def test_invalid_faq_reported_with_index():
    page = _valid_page(faqs=[FAQ("Q?", "A."), FAQ("", "A2.")])
    errors = page.validate()
    assert any("FAQ 2" in e for e in errors)


# --- social fallback -------------------------------------------------------


def test_social_fallback_to_seo():
    page = _valid_page()
    assert page.effective_social_title() == page.seo_title
    assert page.effective_social_description() == page.seo_description
    assert page.social_title_is_fallback()
    assert page.social_description_is_fallback()


def test_social_explicit_values_used():
    page = _valid_page(
        social_title="Social T", social_description="Social D"
    )
    assert page.effective_social_title() == "Social T"
    assert page.effective_social_description() == "Social D"
    assert not page.social_title_is_fallback()
    assert not page.social_description_is_fallback()


# --- ImageRef --------------------------------------------------------------


def test_imageref_unresolved_by_default():
    ref = ImageRef(filename="001-butter-chicken.jpg")
    assert ref.filename == "001-butter-chicken.jpg"
    assert ref.local_path is None
    assert not ref.is_resolved()


def test_imageref_resolved():
    ref = ImageRef(filename="x.jpg", local_path="/cache/x.jpg")
    assert ref.is_resolved()


# --- PageResult status branches (all reachable) ----------------------------


def test_status_success_all_sections_true():
    sections = {
        SECTION_BASIC_INFO: True,
        SECTION_SEO_METADATA: True,
        SECTION_SOCIAL_METADATA: True,
        SECTION_CONTENT: True,
        SECTION_FAQ: True,
    }
    result = PageResult.from_sections("P", "/p", sections)
    assert result.status == STATUS_SUCCESS
    assert result.is_success and result.created


def test_status_partial_optional_section_failed():
    sections = {
        SECTION_BASIC_INFO: True,
        SECTION_SEO_METADATA: True,
        SECTION_FAQ: False,
    }
    result = PageResult.from_sections("P", "/p", sections)
    assert result.status == STATUS_PARTIAL
    assert result.is_partial and result.created


def test_status_failed_critical_section_failed():
    sections = {
        SECTION_BASIC_INFO: True,
        SECTION_SEO_METADATA: False,
    }
    result = PageResult.from_sections("P", "/p", sections)
    assert result.status == STATUS_FAILED
    assert result.is_failed and not result.created


def test_status_failed_no_sections():
    result = PageResult.from_sections("P", "/p", {})
    assert result.status == STATUS_FAILED


def test_status_skipped():
    result = PageResult.skipped_result("P", "/p")
    assert result.status == STATUS_SKIPPED
    assert result.is_skipped and not result.created


def test_failed_result_constructor_carries_error():
    result = PageResult.failed_result("P", "/p", error="boom")
    assert result.is_failed
    assert result.error == "boom"


def test_invalid_status_rejected():
    with pytest.raises(ValueError):
        PageResult(page_name="P", href="/p", status="bogus")


def test_compute_status_partial_when_only_optional_present_and_true():
    # Criticals absent but present-optional all true -> success (all True).
    sections = {SECTION_CONTENT: True}
    assert PageResult.compute_status(sections) == STATUS_SUCCESS


# --- BatchResult aggregation -----------------------------------------------


def test_batch_aggregation():
    batch = BatchResult()
    batch.add(
        PageResult.from_sections(
            "A", "/a", {SECTION_BASIC_INFO: True, SECTION_SEO_METADATA: True}
        )
    )  # success
    batch.add(
        PageResult.from_sections(
            "B",
            "/b",
            {
                SECTION_BASIC_INFO: True,
                SECTION_SEO_METADATA: True,
                SECTION_FAQ: False,
            },
        )
    )  # partial
    batch.add(
        PageResult.from_sections(
            "C", "/c", {SECTION_BASIC_INFO: False, SECTION_SEO_METADATA: True}
        )
    )  # failed
    batch.add(PageResult.skipped_result("D", "/d"))  # skipped

    assert batch.total == 4
    assert batch.success == 1
    assert batch.partial == 1
    assert batch.failed == 1
    assert batch.skipped == 1
    assert batch.created == 2
    assert batch.summary() == {
        "total": 4,
        "success": 1,
        "partial": 1,
        "failed": 1,
        "skipped": 1,
    }


def test_batch_empty():
    batch = BatchResult()
    assert batch.total == 0
    assert batch.summary()["total"] == 0
