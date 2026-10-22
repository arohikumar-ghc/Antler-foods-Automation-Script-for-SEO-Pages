"""Offline tests for reporting (duration formatting + E:G cell values)."""
import pytest

from antler_seo.models import (
    FAQ, PageResult, SEOPage,
    SECTION_BASIC_INFO, SECTION_SEO_METADATA, SECTION_CONTENT, SECTION_FAQ,
)
from antler_seo.reporting import RestaurantResult, format_duration


def _ok_sections():
    return {
        SECTION_BASIC_INFO: True, SECTION_SEO_METADATA: True,
        SECTION_CONTENT: True, SECTION_FAQ: True,
    }


def _success_page(href):
    return PageResult.from_sections(f"P{href}", href, _ok_sections())


def _complete_result(n=10, elapsed=None):
    r = RestaurantResult(restaurant_name="R", row_number=2, source_doc="d")
    r.reached_processing = True
    for i in range(n):
        r.add_page(_success_page(f"/p{i}"))
    r.elapsed_seconds = elapsed
    return r


# --- format_duration -------------------------------------------------------


@pytest.mark.parametrize(
    "seconds,expected",
    [
        (None, ""),
        (0, "0 sec"),
        (42, "42 sec"),
        (59, "59 sec"),
        (60, "1 min 0 sec"),
        (70, "1 min 10 sec"),
        (310, "5 min 10 sec"),
        (310.4, "5 min 10 sec"),
        (-3, "0 sec"),
    ],
)
def test_format_duration(seconds, expected):
    assert format_duration(seconds) == expected


# --- completed_cell (column E) ---------------------------------------------


def test_completed_cell_complete_plural():
    r = _complete_result(n=10)
    assert r.is_complete
    assert r.completed_cell() == "10 pages created"
    assert "INCOMPLETE" not in r.completed_cell()


def test_completed_cell_complete_singular():
    r = _complete_result(n=1)
    assert r.completed_cell() == "1 page created"


def test_completed_cell_counts_only_created_not_skipped_or_failed():
    r = RestaurantResult(restaurant_name="R", row_number=2)
    r.reached_processing = True
    r.add_page(_success_page("/a"))                              # success
    r.add_page(PageResult.skipped_result("S", "/s"))            # skipped
    r.add_page(PageResult.failed_result("F", "/f", error="x"))  # failed
    # Not complete (a failed page) -> INCOMPLETE prefix, count = 1 created only.
    assert r.success == 1 and r.skipped == 1 and r.failed == 1
    assert r.completed_cell() == "INCOMPLETE: 1 page created"


def test_completed_cell_partial_is_incomplete():
    r = RestaurantResult(restaurant_name="R", row_number=2)
    r.reached_processing = True
    s = _ok_sections(); s[SECTION_FAQ] = False
    r.add_page(PageResult.from_sections("P", "/p", s))  # partial
    assert not r.is_complete
    assert r.completed_cell().startswith("INCOMPLETE:")


# --- elapsed_cell (column F) ------------------------------------------------


def test_elapsed_cell():
    assert _complete_result(elapsed=310).elapsed_cell() == "5 min 10 sec"
    assert _complete_result(elapsed=42).elapsed_cell() == "42 sec"
    assert _complete_result(elapsed=None).elapsed_cell() == ""


# --- notes (column G) ------------------------------------------------------


def test_notes_complete_flags_complete():
    note = _complete_result(n=3).notes()
    assert note.startswith("Complete:")
    assert "created 3" in note


def test_notes_incomplete_flags_incomplete_and_counts():
    r = RestaurantResult(restaurant_name="R", row_number=2)
    r.reached_processing = True
    r.add_page(_success_page("/a"))
    r.add_page(PageResult.failed_result("F", "/f", error="boom"))
    note = r.notes()
    assert note.startswith("INCOMPLETE:")
    assert "created 1" in note and "failed 1" in note


def test_notes_pre_processing_failure():
    r = RestaurantResult(restaurant_name="R", row_number=2)
    r.add_error("Google Doc Link is required")
    note = r.notes()
    assert "Failed before processing" in note
