"""
Google Sheet reader for the batch control panel.

The Sheet is the batch-level work list: one row per restaurant, with a link to
that restaurant's Google Doc of SEO pages. Columns (A–G):

    A Restaurant Name
    B Google Doc Link
    C Image Folder Link
    D No. of Pages
    E Completed
    F Last Run
    G Notes

A row is *pending* when ``Completed`` (trimmed + lowercased) is NOT one of
``yes`` / ``y`` / ``completed`` (empty counts as pending).

The row-parsing core (:func:`parse_rows`) is pure and network-free so it is
fully unit-testable; :class:`GoogleSheetReader` wraps a Google Sheets service
for live reads. Google libraries are imported lazily. This phase is READ-ONLY —
no status writeback.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Sequence

from antler_seo.logging_setup import get_logger

logger = get_logger("input.google_sheet")

# Statuses (normalized) that mean a row is already done.
_COMPLETED_VALUES = frozenset({"yes", "y", "completed"})

# New success format written to column E, e.g. "10 pages created" / "1 page
# created". A row with this exact shape is treated as COMPLETED (not pending).
# An "INCOMPLETE: ..." marker (partial run) does NOT match, so it stays pending
# and will be retried.
_PAGES_CREATED_RE = re.compile(r"^\d+\s+pages?\s+created$")


def _is_completed_cell(value: str) -> bool:
    """True if the Completed cell indicates the row is done.

    Backward-compatible: legacy ``yes`` / ``y`` / ``completed`` still count, and
    the new ``N pages created`` success format also counts. Empty, ``no``,
    ``INCOMPLETE: ...`` and anything else mean pending.
    """
    v = (value or "").strip().lower()
    if not v:
        return False
    if v in _COMPLETED_VALUES:
        return True
    return bool(_PAGES_CREATED_RE.match(v))

_SPREADSHEET_ID_RE = re.compile(r"/spreadsheets/d/([a-zA-Z0-9-_]+)")
_BARE_ID_RE = re.compile(r"^[a-zA-Z0-9-_]{20,}$")

DEFAULT_SHEET_NAME = "Sheet1"


class SheetError(Exception):
    """Raised when the Google Sheet cannot be read or addressed."""


class SheetWriteError(Exception):
    """Raised when a status write-back to the Google Sheet fails."""


def extract_spreadsheet_id(url_or_id: str) -> str:
    """Extract a spreadsheet id from a full URL or accept a bare id.

    Raises:
        SheetError: If no id can be determined.
    """
    value = (url_or_id or "").strip()
    if not value:
        raise SheetError("Empty spreadsheet URL/id")

    match = _SPREADSHEET_ID_RE.search(value)
    if match:
        return match.group(1)
    if _BARE_ID_RE.match(value):
        return value
    raise SheetError(f"Could not extract spreadsheet id from: {url_or_id!r}")


@dataclass
class RestaurantRow:
    """One restaurant row from the control-panel Sheet.

    ``row_number`` is the 1-based Sheet row (preserved so a later phase can
    write status back to the correct row).
    """

    row_number: int
    restaurant_name: str
    doc_link: str
    image_folder: str
    no_of_pages: str
    completed: str
    last_run: str
    notes: str

    @property
    def is_pending(self) -> bool:
        return not _is_completed_cell(self.completed)

    @property
    def page_count(self) -> Optional[int]:
        """Declared page count as an int, or ``None`` if blank/non-numeric."""
        raw = (self.no_of_pages or "").strip()
        if not raw:
            return None
        try:
            return int(raw)
        except ValueError:
            return None

    @property
    def has_doc_link(self) -> bool:
        return bool((self.doc_link or "").strip())


def _cell(row: Sequence[str], index: int) -> str:
    """Return a trimmed cell value, tolerating short/ragged rows."""
    if index < len(row):
        return (row[index] or "").strip()
    return ""


def parse_rows(
    values: Sequence[Sequence[str]],
    header_row: int = 1,
) -> List[RestaurantRow]:
    """Convert raw Sheet ``values`` (including the header) into rows.

    Pure and network-free. The first ``header_row`` rows are treated as headers
    and skipped. Blank rows (no restaurant name) are dropped. The 1-based Sheet
    row number is preserved on each :class:`RestaurantRow`.

    Args:
        values: Rows as returned by the Sheets API ``values`` field (a list of
            lists of strings), including the header row(s).
        header_row: Number of leading header rows to skip (default 1).

    Returns:
        A list of :class:`RestaurantRow`.
    """
    rows: List[RestaurantRow] = []
    for offset, raw in enumerate(values):
        sheet_row_number = offset + 1  # 1-based, matches the Sheet
        if sheet_row_number <= header_row:
            continue
        name = _cell(raw, 0)
        if not name:
            continue  # skip blank/separator rows
        rows.append(
            RestaurantRow(
                row_number=sheet_row_number,
                restaurant_name=name,
                doc_link=_cell(raw, 1),
                image_folder=_cell(raw, 2),
                no_of_pages=_cell(raw, 3),
                completed=_cell(raw, 4),
                last_run=_cell(raw, 5),
                notes=_cell(raw, 6),
            )
        )
    return rows


def build_sheets_service(credentials):
    """Build a Google Sheets API service from credentials (lazy import)."""
    try:
        from googleapiclient.discovery import build  # type: ignore
    except Exception as exc:  # pragma: no cover - exercised when lib absent
        raise SheetError(
            "Google API client is not installed. Install it with "
            "`pip install -r requirements.txt`."
        ) from exc
    return build("sheets", "v4", credentials=credentials, cache_discovery=False)


class GoogleSheetReader:
    """Reads restaurant rows from a Google Sheet via a Sheets service."""

    def __init__(self, service):
        self.service = service

    def read_rows(
        self,
        spreadsheet_url_or_id: str,
        sheet_name: str = DEFAULT_SHEET_NAME,
        header_row: int = 1,
    ) -> List[RestaurantRow]:
        """Read and parse all restaurant rows from the Sheet."""
        spreadsheet_id = extract_spreadsheet_id(spreadsheet_url_or_id)
        range_name = f"{sheet_name}!A:G"
        logger.info("Reading sheet %s range %s", spreadsheet_id, range_name)
        try:
            result = (
                self.service.spreadsheets()
                .values()
                .get(spreadsheetId=spreadsheet_id, range=range_name)
                .execute()
            )
        except Exception as exc:
            raise SheetError(f"Failed to read Google Sheet: {exc}") from exc

        values = result.get("values", [])
        rows = parse_rows(values, header_row=header_row)
        logger.info("Parsed %d restaurant row(s)", len(rows))
        return rows

    def pending_rows(
        self,
        spreadsheet_url_or_id: str,
        sheet_name: str = DEFAULT_SHEET_NAME,
        header_row: int = 1,
    ) -> List[RestaurantRow]:
        """Return only the rows that are still pending."""
        pending = [
            r
            for r in self.read_rows(spreadsheet_url_or_id, sheet_name, header_row)
            if r.is_pending
        ]
        logger.info("%d pending restaurant row(s)", len(pending))
        return pending

    def read_status_cells(
        self,
        spreadsheet_url_or_id: str,
        row_number: int,
        sheet_name: str = DEFAULT_SHEET_NAME,
    ) -> List[str]:
        """Read back the status cells (columns E:G) of a single row.

        Returns a list ``[completed, last_run, notes]``, padded to length 3 with
        empty strings. Used to verify (and, in the live test, restore) a write.
        """
        if row_number < 1:
            raise SheetError(f"row_number must be >= 1, got {row_number}")
        spreadsheet_id = extract_spreadsheet_id(spreadsheet_url_or_id)
        range_name = f"{sheet_name}!E{row_number}:G{row_number}"
        try:
            result = (
                self.service.spreadsheets()
                .values()
                .get(spreadsheetId=spreadsheet_id, range=range_name)
                .execute()
            )
        except Exception as exc:
            raise SheetError(f"Failed to read status cells: {exc}") from exc
        values = result.get("values", [])
        row = values[0] if values else []
        return [(_cell(row, i)) for i in range(3)]


class GoogleSheetWriter:
    """Writes per-row processing status back to the control Sheet.

    Deliberately narrow: the ONLY operation is :meth:`write_status`, which
    updates columns **E:G of one specific row** (Completed, Last Run, Notes).
    It never touches columns A:D, never accepts an arbitrary range, and exposes
    no generic ``batchUpdate``/write method. Row targeting always uses the
    caller-supplied ``row_number`` (from :class:`RestaurantRow`).

    Status write-back into the pipeline is intentionally NOT wired yet:
    ``Completed=Yes`` must represent success of the full automation (including
    the future Antler CMS step), not merely parse/validate.
    """

    #: Columns written by this writer (status columns only).
    STATUS_COLUMNS = "E:G"

    def __init__(self, service):
        self.service = service

    def write_status(
        self,
        spreadsheet_url_or_id: str,
        row_number: int,
        *,
        completed: str,
        last_run: str,
        notes: str,
        sheet_name: str = DEFAULT_SHEET_NAME,
    ) -> str:
        """Write Completed/Last Run/Notes to columns E:G of a single row.

        Args:
            spreadsheet_url_or_id: Sheet URL or id (from config/.env).
            row_number: 1-based Sheet row to update (never a range).
            completed: Value for column E (e.g. ``"Yes"``/``"No"``).
            last_run: Value for column F (timestamp string; supplied by caller).
            notes: Value for column G (short outcome string).
            sheet_name: Worksheet/tab name (default ``Sheet1``).

        Returns:
            The exact A1 range written (e.g. ``"Sheet1!E2:G2"``).

        Raises:
            SheetWriteError: If ``row_number`` is invalid or the update fails.
        """
        if row_number is None or int(row_number) < 2:
            # Row 1 is the header; refuse to overwrite it.
            raise SheetWriteError(
                f"Refusing to write status to row {row_number!r}; the first "
                f"data row is 2 (row 1 is the header)."
            )

        spreadsheet_id = extract_spreadsheet_id(spreadsheet_url_or_id)
        range_name = f"{sheet_name}!E{row_number}:G{row_number}"
        body = {"values": [[completed, last_run, notes]]}

        logger.info("Writing status to %s", range_name)
        try:
            self.service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range=range_name,
                valueInputOption="RAW",
                body=body,
            ).execute()
        except Exception as exc:
            raise SheetWriteError(
                f"Failed to write status to row {row_number}: {exc}"
            ) from exc

        logger.info("Status written to %s", range_name)
        return range_name
