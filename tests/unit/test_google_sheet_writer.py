"""Unit tests for GoogleSheetWriter (offline, mocked; no network)."""
import pytest

from antler_seo.input.google_sheet import (
    GoogleSheetReader,
    GoogleSheetWriter,
    SheetWriteError,
)

SHEET = "https://docs.google.com/spreadsheets/d/SID/edit"


class FakeValues:
    """Records update()/get() calls for a fake Sheets service."""

    def __init__(self, store):
        self._store = store

    def update(self, spreadsheetId, range, valueInputOption, body):  # noqa: N803
        self._store["update_calls"].append(
            {
                "spreadsheetId": spreadsheetId,
                "range": range,
                "valueInputOption": valueInputOption,
                "body": body,
            }
        )
        return self

    def get(self, spreadsheetId, range):  # noqa: N803
        self._store["get_calls"].append({"spreadsheetId": spreadsheetId, "range": range})
        self._store["last_get_range"] = range
        return self

    def execute(self):
        # For update: return a benign response. For get: return canned cells.
        return {"values": self._store.get("get_values", [])}


class FakeSpreadsheets:
    def __init__(self, store):
        self._store = store

    def values(self):
        return FakeValues(self._store)


class FakeService:
    def __init__(self, store=None, raise_on_access=False):
        self._store = store if store is not None else {
            "update_calls": [], "get_calls": []
        }
        self._raise = raise_on_access

    def spreadsheets(self):
        if self._raise:
            raise RuntimeError("api down")
        return FakeSpreadsheets(self._store)


def _store():
    return {"update_calls": [], "get_calls": []}


# --- write_status: correct range, body, columns ---------------------------


def test_write_status_targets_single_row_eg():
    store = _store()
    writer = GoogleSheetWriter(FakeService(store))
    rng = writer.write_status(
        SHEET, 2, completed="Yes", last_run="2026-10-08 10:00:00", notes="OK: 10 pages"
    )
    assert rng == "Sheet1!E2:G2"
    assert len(store["update_calls"]) == 1
    call = store["update_calls"][0]
    assert call["range"] == "Sheet1!E2:G2"
    assert call["valueInputOption"] == "RAW"
    assert call["body"] == {
        "values": [["Yes", "2026-10-08 10:00:00", "OK: 10 pages"]]
    }
    assert call["spreadsheetId"] == "SID"


def test_write_status_uses_supplied_row_number():
    store = _store()
    writer = GoogleSheetWriter(FakeService(store))
    writer.write_status(SHEET, 7, completed="No", last_run="t", notes="err")
    assert store["update_calls"][0]["range"] == "Sheet1!E7:G7"


def test_write_status_custom_sheet_name():
    store = _store()
    writer = GoogleSheetWriter(FakeService(store))
    rng = writer.write_status(
        SHEET, 3, completed="Yes", last_run="t", notes="n", sheet_name="Data"
    )
    assert rng == "Data!E3:G3"
    assert store["update_calls"][0]["range"] == "Data!E3:G3"


def test_write_status_never_touches_a_to_d():
    store = _store()
    writer = GoogleSheetWriter(FakeService(store))
    writer.write_status(SHEET, 5, completed="Yes", last_run="t", notes="n")
    rng = store["update_calls"][0]["range"]
    # Range must start at column E and the body is exactly 3 columns (E,F,G).
    assert "!E" in rng
    for col in ("A", "B", "C", "D"):
        assert f"!{col}" not in rng
    assert len(store["update_calls"][0]["body"]["values"][0]) == 3


# --- row-number guards -----------------------------------------------------


@pytest.mark.parametrize("bad_row", [1, 0, -1, None])
def test_write_status_rejects_header_and_invalid_rows(bad_row):
    writer = GoogleSheetWriter(FakeService())
    with pytest.raises(SheetWriteError):
        writer.write_status(SHEET, bad_row, completed="Yes", last_run="t", notes="n")


# --- error isolation / wrapping --------------------------------------------


def test_write_status_wraps_api_errors():
    writer = GoogleSheetWriter(FakeService(raise_on_access=True))
    with pytest.raises(SheetWriteError):
        writer.write_status(SHEET, 2, completed="Yes", last_run="t", notes="n")


# --- no generic write surface ----------------------------------------------


def test_writer_exposes_only_write_status():
    public = [
        n
        for n in dir(GoogleSheetWriter)
        if not n.startswith("_") and callable(getattr(GoogleSheetWriter, n))
    ]
    assert public == ["write_status"]
    # No generic batchUpdate/arbitrary-range method.
    assert not hasattr(GoogleSheetWriter, "batchUpdate")
    assert not hasattr(GoogleSheetWriter, "update")
    assert not hasattr(GoogleSheetWriter, "write_range")


# --- read_status_cells (used by the live test to verify/restore) -----------


def test_read_status_cells_pads_to_three():
    store = _store()
    store["get_values"] = [["Yes"]]  # only E populated
    reader = GoogleSheetReader(FakeService(store))
    cells = reader.read_status_cells(SHEET, 2)
    assert cells == ["Yes", "", ""]
    assert store["get_calls"][0]["range"] == "Sheet1!E2:G2"


def test_read_status_cells_full_row():
    store = _store()
    store["get_values"] = [["No", "2026-10-08", "note"]]
    reader = GoogleSheetReader(FakeService(store))
    assert reader.read_status_cells(SHEET, 4) == ["No", "2026-10-08", "note"]


def test_read_status_cells_empty():
    store = _store()
    store["get_values"] = []
    reader = GoogleSheetReader(FakeService(store))
    assert reader.read_status_cells(SHEET, 2) == ["", "", ""]
