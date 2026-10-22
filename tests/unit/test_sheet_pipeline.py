"""Unit tests for the Google Sheet to Doc to parse to validate pipeline (offline)."""
import pytest

from antler_seo.input.google_sheet import RestaurantRow
from antler_seo.input.sheet_pipeline import (
    ROW_STATUS_ERROR,
    ROW_STATUS_OK,
    RowResult,
    process_pending_rows,
    process_row,
)

DOC_URL = "https://docs.google.com/document/d/DID/edit"


def _page_block(name, href, restaurant_header=None, faqs=1):
    lines = []
    if restaurant_header is not None:
        lines.append("Restaurant: " + restaurant_header)
        lines.append("")
    lines += [
        "=== PAGE START ===",
        "Page Name: " + name,
        "Href: " + href,
        "SEO Title: " + name + " Title",
        "SEO Description: " + name + " description text.",
        "Subtitle: Sub",
        "Title: Heading",
        "Description: Body copy.",
    ]
    for i in range(1, faqs + 1):
        lines.append("FAQ Question " + str(i) + ": Q" + str(i) + "?")
        lines.append("FAQ Answer " + str(i) + ": A" + str(i) + ".")
    lines.append("=== PAGE END ===")
    return "\n".join(lines)


ONE_PAGE_DOC = _page_block("About", "/about")
TWO_PAGE_DOC = ONE_PAGE_DOC + "\n\n" + _page_block("Menu", "/menu")


class FakeDocReader:
    """Doc reader stand-in. Counts fetches so we can assert single-fetch."""

    def __init__(self, text="", error=None):
        self._text = text
        self._error = error
        self.fetch_count = 0

    def fetch_text(self, url_or_id):
        self.fetch_count += 1
        if self._error is not None:
            raise self._error
        return self._text


class FakeSheetReader:
    """Returns preset RestaurantRow objects; satisfies pending_rows()."""

    def __init__(self, rows):
        self._rows = rows

    def pending_rows(self, spreadsheet_url_or_id, sheet_name="Sheet1"):
        return [r for r in self._rows if r.is_pending]


def _row(
    row_number=2,
    restaurant_name="Renovo",
    doc_link=DOC_URL,
    image_folder="https://drive/folder",
    no_of_pages="",
    completed="",
    last_run="",
    notes="",
):
    return RestaurantRow(
        row_number=row_number,
        restaurant_name=restaurant_name,
        doc_link=doc_link,
        image_folder=image_folder,
        no_of_pages=no_of_pages,
        completed=completed,
        last_run=last_run,
        notes=notes,
    )


def _factory(reader):
    return lambda: reader


def test_process_row_ok_single_page():
    reader = FakeDocReader(text=ONE_PAGE_DOC)
    result = process_row(_row(no_of_pages="1"), _factory(reader))
    assert result.is_ok
    assert result.status == ROW_STATUS_OK
    assert len(result.pages) == 1
    assert result.outcome.restaurant_name == "Renovo"
    assert result.row_number == 2
    assert result.image_folder_link == "https://drive/folder"


def test_process_row_fetches_doc_exactly_once():
    reader = FakeDocReader(text=ONE_PAGE_DOC)
    process_row(_row(), _factory(reader))
    assert reader.fetch_count == 1


def test_missing_restaurant_name_is_row_error():
    reader = FakeDocReader(text=ONE_PAGE_DOC)
    result = process_row(_row(restaurant_name="  "), _factory(reader))
    assert result.status == ROW_STATUS_ERROR
    assert any("Restaurant Name" in e for e in result.errors)
    assert reader.fetch_count == 0


def test_missing_doc_link_is_row_error():
    reader = FakeDocReader(text=ONE_PAGE_DOC)
    result = process_row(_row(doc_link=""), _factory(reader))
    assert result.status == ROW_STATUS_ERROR
    assert any("Google Doc Link" in e for e in result.errors)
    assert reader.fetch_count == 0


def test_sheet_restaurant_name_is_authoritative_on_mismatch():
    doc = _page_block("About", "/about", restaurant_header="DifferentName")
    reader = FakeDocReader(text=doc)
    result = process_row(_row(restaurant_name="Renovo"), _factory(reader))
    assert result.outcome.restaurant_name == "Renovo"
    assert any("mismatch" in w.lower() for w in result.warnings)
    assert result.is_ok


def test_no_mismatch_warning_when_doc_matches():
    doc = _page_block("About", "/about", restaurant_header="Renovo")
    reader = FakeDocReader(text=doc)
    result = process_row(_row(restaurant_name="Renovo"), _factory(reader))
    assert not any("mismatch" in w.lower() for w in result.warnings)


def test_no_mismatch_warning_when_doc_has_no_restaurant():
    reader = FakeDocReader(text=ONE_PAGE_DOC)
    result = process_row(_row(restaurant_name="Renovo"), _factory(reader))
    assert not any("mismatch" in w.lower() for w in result.warnings)


def test_page_count_empty_does_not_fail():
    reader = FakeDocReader(text=ONE_PAGE_DOC)
    result = process_row(_row(no_of_pages=""), _factory(reader))
    assert result.is_ok


def test_page_count_match_ok():
    reader = FakeDocReader(text=TWO_PAGE_DOC)
    result = process_row(_row(no_of_pages="2"), _factory(reader))
    assert result.is_ok
    assert len(result.pages) == 2


def test_page_count_mismatch_is_row_error():
    reader = FakeDocReader(text=ONE_PAGE_DOC)
    result = process_row(_row(no_of_pages="3"), _factory(reader))
    assert result.status == ROW_STATUS_ERROR
    assert any("No. of Pages mismatch" in e for e in result.errors)


def test_page_count_non_numeric_is_warning_not_error():
    reader = FakeDocReader(text=ONE_PAGE_DOC)
    result = process_row(_row(no_of_pages="many"), _factory(reader))
    assert result.is_ok
    assert any("not a number" in w for w in result.warnings)


def test_doc_fetch_failure_is_isolated_row_error():
    reader = FakeDocReader(error=RuntimeError("network down"))
    result = process_row(_row(), _factory(reader))
    assert result.status == ROW_STATUS_ERROR
    assert any("Failed to read Google Doc" in e for e in result.errors)


def test_malformed_doc_pages_recorded_as_warnings():
    bad = "\n".join(
        ["=== PAGE START ===", "Page Name: Broken", "SEO Title: X", "=== PAGE END ==="]
    )
    reader = FakeDocReader(text=bad)
    result = process_row(_row(), _factory(reader))
    assert result.status == ROW_STATUS_ERROR
    assert result.outcome is not None
    assert result.outcome.pages == []
    assert any("Doc page 1" in w for w in result.warnings)


def test_validation_failure_marks_row_error_but_keeps_outcome():
    dup = _page_block("A", "/dupe") + "\n\n" + _page_block("B", "/dupe")
    reader = FakeDocReader(text=dup)
    result = process_row(_row(no_of_pages="2"), _factory(reader))
    assert result.status == ROW_STATUS_ERROR
    assert result.validation is not None
    assert not result.validation.passed


def test_validate_false_skips_validation():
    dup = _page_block("A", "/dupe") + "\n\n" + _page_block("B", "/dupe")
    reader = FakeDocReader(text=dup)
    result = process_row(_row(no_of_pages="2"), _factory(reader), validate=False)
    assert result.validation is None
    assert result.is_ok


def test_pending_rows_processed_and_completed_excluded():
    rows = [
        _row(row_number=2, restaurant_name="Renovo", completed=""),
        _row(row_number=3, restaurant_name="Done", completed="yes"),
        _row(row_number=4, restaurant_name="Palle", completed="Completed"),
    ]
    reader = FakeDocReader(text=ONE_PAGE_DOC)
    results = process_pending_rows(FakeSheetReader(rows), _factory(reader), "sheet-url")
    assert [r.restaurant_name for r in results] == ["Renovo"]


def test_one_bad_row_does_not_stop_others():
    rows = [
        _row(row_number=2, restaurant_name="GoodA", doc_link=DOC_URL),
        _row(row_number=3, restaurant_name="Bad", doc_link=""),
        _row(row_number=4, restaurant_name="GoodB", doc_link=DOC_URL),
    ]
    reader = FakeDocReader(text=ONE_PAGE_DOC)
    results = process_pending_rows(FakeSheetReader(rows), _factory(reader), "sheet-url")
    assert len(results) == 3
    by_name = {r.restaurant_name: r for r in results}
    assert by_name["GoodA"].is_ok
    assert by_name["GoodB"].is_ok
    assert by_name["Bad"].status == ROW_STATUS_ERROR


def test_row_result_rejects_invalid_status():
    with pytest.raises(ValueError):
        RowResult(
            row_number=1,
            restaurant_name="R",
            doc_link="d",
            image_folder_link="",
            no_of_pages="",
            status="bogus",
        )
