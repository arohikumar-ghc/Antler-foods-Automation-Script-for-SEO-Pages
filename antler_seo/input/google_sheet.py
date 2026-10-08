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

_SPREADSHEET_ID_RE = re.compile(r"/spreadsheets/d/([a-zA-Z0-9-_]+)")
_BARE_ID_RE = re.compile(r"^[a-zA-Z0-9-_]{20,}$")

DEFAULT_SHEET_NAME = "Sheet1"


class SheetError(Exception):
    """Raised when the Google Sheet cannot be read or addressed."""


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


def _normalize_completed(value: str) -> str:
    return (value or "").strip().lower()


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
        return _normalize_completed(self.completed) not in _COMPLETED_VALUES

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
