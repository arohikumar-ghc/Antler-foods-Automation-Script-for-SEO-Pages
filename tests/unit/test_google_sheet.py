"""Unit tests for the Google Sheet reader (no network)."""
import pytest

from antler_seo.input.google_sheet import (
    GoogleSheetReader,
    RestaurantRow,
    SheetError,
    extract_spreadsheet_id,
    parse_rows,
)

HEADER = [
    "Restaurant Name",
    "Google Doc Link",
    "Image Folder Link",
    "No. of Pages",
    "Completed",
    "Last Run",
    "Notes",
]


class FakeSheetService:
    """Stand-in for the Google Sheets service.

    When raise_on_access is True, spreadsheets() raises to simulate an API
    failure. Otherwise values().get(...).execute() returns the given rows.
    """

    def __init__(self, values=None, raise_on_access=False):
        self._values = values or []
        self._raise = raise_on_access

    def spreadsheets(self):
        if self._raise:
            raise RuntimeError("api down")
        return self

    def values(self):
        return self

    def get(self, spreadsheetId, range):
        self._requested = (spreadsheetId, range)
        return self

    def execute(self):
        return {"values": self._values}


def make_row(completed="", no_of_pages=""):
    return RestaurantRow(
        row_number=2,
        restaurant_name="R",
        doc_link="d",
        image_folder="",
        no_of_pages=no_of_pages,
        completed=completed,
        last_run="",
        notes="",
    )


def test_extract_id_from_url():
    url = "https://docs.google.com/spreadsheets/d/1AbC-_dEf123/edit#gid=0"
    assert extract_spreadsheet_id(url) == "1AbC-_dEf123"


def test_extract_id_accepts_bare_id():
    assert extract_spreadsheet_id("1AbCdefGHIjklMNOpqrstUVWxyz") == "1AbCdefGHIjklMNOpqrstUVWxyz"


@pytest.mark.parametrize("bad", ["", "   ", "not a url", "https://example.com/x"])
def test_extract_id_invalid(bad):
    with pytest.raises(SheetError):
        extract_spreadsheet_id(bad)


def test_parse_rows_maps_columns_and_row_numbers():
    values = [
        HEADER,
        ["Renovo", "https://docs.google.com/document/d/DID/edit", "https://drive/folder", "3", "", "", "note"],
    ]
    rows = parse_rows(values)
    assert len(rows) == 1
    r = rows[0]
    assert r.row_number == 2
    assert r.restaurant_name == "Renovo"
    assert r.doc_link.endswith("/edit")
    assert r.image_folder == "https://drive/folder"
    assert r.no_of_pages == "3"
    assert r.page_count == 3
    assert r.notes == "note"
    assert r.is_pending
    assert r.has_doc_link


def test_parse_rows_skips_blank_rows_but_keeps_row_numbers():
    values = [
        HEADER,
        ["", "", "", "", "", "", ""],
        ["Palle Ruchi", "doc", "", "", "", "", ""],
    ]
    rows = parse_rows(values)
    assert len(rows) == 1
    assert rows[0].restaurant_name == "Palle Ruchi"
    assert rows[0].row_number == 3


def test_parse_rows_tolerates_short_rows():
    rows = parse_rows([HEADER, ["OnlyName"]])
    assert rows[0].restaurant_name == "OnlyName"
    assert rows[0].doc_link == ""
    assert rows[0].page_count is None


def test_parse_rows_trims_whitespace():
    rows = parse_rows([HEADER, ["  Renovo  ", "  doc  ", "", "", "", "", ""]])
    assert rows[0].restaurant_name == "Renovo"
    assert rows[0].doc_link == "doc"


def test_parse_rows_empty_values():
    assert parse_rows([]) == []
    assert parse_rows([HEADER]) == []


@pytest.mark.parametrize(
    "completed,pending",
    [
        ("", True),
        ("   ", True),
        ("no", True),
        ("pending", True),
        ("in progress", True),
        ("yes", False),
        ("Yes", False),
        ("  YES  ", False),
        ("y", False),
        ("Y", False),
        ("completed", False),
        ("Completed", False),
        ("COMPLETED", False),
    ],
)
def test_pending_normalization(completed, pending):
    assert make_row(completed=completed).is_pending is pending


def test_page_count_parses_or_none():
    assert make_row(no_of_pages="3").page_count == 3
    assert make_row(no_of_pages="").page_count is None
    assert make_row(no_of_pages="   ").page_count is None
    assert make_row(no_of_pages="many").page_count is None


def test_reader_read_rows():
    values = [
        HEADER,
        ["Renovo", "doc1", "", "2", "", "", ""],
        ["Palle Ruchi", "doc2", "", "1", "yes", "", ""],
    ]
    reader = GoogleSheetReader(FakeSheetService(values))
    rows = reader.read_rows("https://docs.google.com/spreadsheets/d/SID/edit")
    assert [r.restaurant_name for r in rows] == ["Renovo", "Palle Ruchi"]


def test_reader_pending_rows_filters_completed():
    values = [
        HEADER,
        ["Renovo", "doc1", "", "2", "", "", ""],
        ["Palle Ruchi", "doc2", "", "1", "yes", "", ""],
        ["Taste", "doc3", "", "", "completed", "", ""],
    ]
    reader = GoogleSheetReader(FakeSheetService(values))
    pending = reader.pending_rows("SID_bare_id_1234567890")
    assert [r.restaurant_name for r in pending] == ["Renovo"]


def test_reader_wraps_api_errors():
    reader = GoogleSheetReader(FakeSheetService(raise_on_access=True))
    with pytest.raises(SheetError):
        reader.read_rows("https://docs.google.com/spreadsheets/d/SID/edit")
