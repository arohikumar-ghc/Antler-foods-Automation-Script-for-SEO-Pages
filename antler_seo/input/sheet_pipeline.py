"""
Google Sheet → Google Doc → parse → validate pipeline.

Connects the existing input components into the business workflow proven by the
Food Amigo reference, implemented with Antler's own architecture:

    GoogleSheetReader.pending_rows()
        → for each pending row (isolated):
            require Restaurant Name + Google Doc Link
            fetch the Doc content ONCE
            extract the Doc-declared restaurant and compare to the Sheet value
            parse with the existing parse_text() (single SEOPage parser)
            force the Sheet Restaurant Name as authoritative
            enforce No. of Pages (row-level error on mismatch; empty = ignore)
            run the existing validation layer
        → list[RowResult]

This module ONLY orchestrates existing pieces. It adds no Google auth, no Sheet
or Doc parsing, and no second SEOPage parser. It performs NO image handling and
NO write-back to Google Sheets (read-only). The Google Doc is fetched exactly
once per row and that single text is reused for both parsing and the
restaurant-mismatch check (so GoogleDocSource.load(), which fetches internally,
is deliberately NOT used here).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional

from antler_seo.input.base import ParseOutcome
from antler_seo.input.google_sheet import GoogleSheetReader, RestaurantRow
from antler_seo.input.local_document import _extract_restaurant_name, parse_text
from antler_seo.logging_setup import get_logger
from antler_seo.validation.validator import ValidationReport, validate_pages

logger = get_logger("input.sheet_pipeline")

ROW_STATUS_OK = "ok"
ROW_STATUS_ERROR = "error"

# A reader factory produces an object with ``fetch_text(url_or_id) -> str``.
# Kept injectable so tests pass a fake with no network, and the live path passes
# a real GoogleDocReader.
DocReaderFactory = Callable[[], object]


@dataclass
class RowResult:
    """Outcome of processing a single Sheet row (isolated from other rows)."""

    row_number: int
    restaurant_name: str
    doc_link: str
    image_folder_link: str
    no_of_pages: str
    status: str = ROW_STATUS_OK
    outcome: Optional[ParseOutcome] = None
    validation: Optional[ValidationReport] = None
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.status not in (ROW_STATUS_OK, ROW_STATUS_ERROR):
            raise ValueError(f"Invalid row status: {self.status!r}")

    @property
    def is_ok(self) -> bool:
        return self.status == ROW_STATUS_OK

    @property
    def pages(self) -> list:
        return list(self.outcome.pages) if self.outcome else []

    def add_error(self, message: str) -> None:
        self.errors.append(message)
        self.status = ROW_STATUS_ERROR


def _restaurants_differ(sheet_name: str, doc_name: Optional[str]) -> bool:
    """True if the Doc declares a restaurant that differs from the Sheet's.

    Comparison is trim + case-insensitive. A Doc with no declared restaurant is
    not a mismatch.
    """
    if not doc_name or not doc_name.strip():
        return False
    return sheet_name.strip().lower() != doc_name.strip().lower()


def process_row(
    row: RestaurantRow,
    doc_reader_factory: DocReaderFactory,
    *,
    validate: bool = True,
    images_enabled: bool = False,
) -> RowResult:
    """Process a single restaurant row end-to-end (Doc → parse → validate).

    Never raises for expected problems: all issues are recorded on the returned
    :class:`RowResult` with ``status == "error"`` so the caller can keep going.

    Args:
        row: A :class:`RestaurantRow` from the Sheet.
        doc_reader_factory: Zero-arg callable returning a Doc reader with
            ``fetch_text(url_or_id) -> str``.
        validate: Whether to run the pre-flight validation layer.
        images_enabled: Passed through to validation (default False; images are
            deferred — no download/processing happens here regardless).

    Returns:
        A :class:`RowResult`.
    """
    result = RowResult(
        row_number=row.row_number,
        restaurant_name=row.restaurant_name,
        doc_link=row.doc_link,
        image_folder_link=row.image_folder,
        no_of_pages=row.no_of_pages,
    )

    # Require Restaurant Name and Google Doc Link.
    if not (row.restaurant_name or "").strip():
        result.add_error("Restaurant Name is required")
        logger.error("Row %d: Restaurant Name is required", row.row_number)
        return result
    if not row.has_doc_link:
        result.add_error("Google Doc Link is required")
        logger.error(
            "Row %d (%s): Google Doc Link is required",
            row.row_number,
            row.restaurant_name,
        )
        return result

    # Fetch the Doc content ONCE. We call the reader + the existing parse_text()
    # directly (instead of GoogleDocSource.load(), which would fetch internally)
    # so the document is fetched only once per row. google_doc.py is unchanged;
    # parse_text is the single SEOPage parser.
    try:
        reader = doc_reader_factory()
        doc_text = reader.fetch_text(row.doc_link)
    except Exception as exc:
        result.add_error(f"Failed to read Google Doc: {exc}")
        logger.error(
            "Row %d (%s): failed to read Google Doc: %s",
            row.row_number,
            row.restaurant_name,
            exc,
        )
        return result

    # Parse the single fetched text with the existing parser.
    try:
        outcome = parse_text(doc_text)
    except Exception as exc:
        result.add_error(f"Failed to parse Google Doc: {exc}")
        logger.error(
            "Row %d (%s): failed to parse Google Doc: %s",
            row.row_number,
            row.restaurant_name,
            exc,
        )
        return result

    result.outcome = outcome

    # Restaurant authority + mismatch diagnostic, from the SAME doc_text (no
    # second fetch). The Sheet value is authoritative.
    doc_declared = _extract_restaurant_name(doc_text)
    if _restaurants_differ(row.restaurant_name, doc_declared):
        msg = (
            f"Restaurant mismatch: Sheet says {row.restaurant_name!r} but Doc "
            f"declares {doc_declared!r}. Using the Sheet value (authoritative)."
        )
        result.warnings.append(msg)
        logger.warning("Row %d: %s", row.row_number, msg)

    # parse_text may have set the outcome's restaurant from the Doc header;
    # overwrite with the Sheet value (authoritative).
    outcome.restaurant_name = row.restaurant_name

    # Surface any per-page parse errors as row warnings (not fatal — malformed
    # pages were isolated by the parser).
    for perr in outcome.errors:
        result.warnings.append(f"Doc page {perr.index}: {perr.message}")

    # No. of Pages: empty → ignore; provided → compare to parsed pages.
    expected = row.page_count
    if expected is not None:
        actual = len(outcome.pages)
        if expected != actual:
            result.add_error(
                f"No. of Pages mismatch: Sheet declares {expected}, "
                f"parsed {actual}"
            )
            logger.error(
                "Row %d (%s): No. of Pages mismatch: declared %d, parsed %d",
                row.row_number,
                row.restaurant_name,
                expected,
                actual,
            )
    elif (row.no_of_pages or "").strip():
        # Non-empty but non-numeric: note it, don't fail the row on count.
        result.warnings.append(
            f"No. of Pages is not a number: {row.no_of_pages!r}"
        )

    # Run the existing validation layer over the parsed pages.
    if validate:
        report = validate_pages(
            outcome.pages,
            expected_page_count=None,  # count enforced above as a row error
            images_enabled=images_enabled,
        )
        result.validation = report
        if not report.passed:
            # Validation failures make the row an error, but we keep going.
            result.status = ROW_STATUS_ERROR
            if not report.pages and report.errors:
                for e in report.errors:
                    result.errors.append(f"Validation: {e}")
            else:
                failed = sum(1 for p in report.pages if not p.passed)
                result.errors.append(f"Validation failed for {failed} page(s)")
            logger.warning(
                "Row %d (%s): validation failed (%d error(s))",
                row.row_number,
                row.restaurant_name,
                report.total_errors(),
            )

    if result.is_ok:
        logger.info(
            "Row %d (%s): OK — %d page(s) parsed",
            row.row_number,
            row.restaurant_name,
            len(outcome.pages),
        )
    return result


def process_pending_rows(
    sheet_reader: GoogleSheetReader,
    doc_reader_factory: DocReaderFactory,
    spreadsheet_url_or_id: str,
    *,
    sheet_name: str = "Sheet1",
    validate: bool = True,
    images_enabled: bool = False,
) -> List[RowResult]:
    """Read pending rows and process each independently.

    One bad row records an error and processing continues to the next row; a
    failure reading the Sheet itself propagates (there is nothing to isolate).

    Args:
        sheet_reader: An existing :class:`GoogleSheetReader`.
        doc_reader_factory: Zero-arg callable returning a Doc reader.
        spreadsheet_url_or_id: Sheet URL or id (supplied by the caller from
            configuration/.env — never hard-coded here).
        sheet_name: Worksheet/tab name (default ``Sheet1``).
        validate: Whether to run validation per row.
        images_enabled: Passed through to validation.

    Returns:
        A list of :class:`RowResult`, one per pending row.
    """
    pending = sheet_reader.pending_rows(spreadsheet_url_or_id, sheet_name=sheet_name)
    logger.info("Processing %d pending row(s)", len(pending))

    results: List[RowResult] = []
    for row in pending:
        try:
            results.append(
                process_row(
                    row,
                    doc_reader_factory,
                    validate=validate,
                    images_enabled=images_enabled,
                )
            )
        except Exception as exc:  # defensive: never let one row stop the batch
            logger.error(
                "Row %d (%s): unexpected error, isolating: %s",
                row.row_number,
                row.restaurant_name,
                exc,
            )
            rr = RowResult(
                row_number=row.row_number,
                restaurant_name=row.restaurant_name,
                doc_link=row.doc_link,
                image_folder_link=row.image_folder,
                no_of_pages=row.no_of_pages,
            )
            rr.add_error(f"Unexpected error: {exc}")
            results.append(rr)

    ok = sum(1 for r in results if r.is_ok)
    logger.info("Pipeline complete: %d ok, %d error(s)", ok, len(results) - ok)
    return results
