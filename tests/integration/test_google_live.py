"""Live integration test for the Google cloud input layer.

Gated: auto-skips unless the OAuth client config and a sheet URL are configured
(ANTLER_GOOGLE_CREDENTIALS_FILE + ANTLER_GOOGLE_SHEET_URL, loaded from .env).
Reads the real Sheet, finds the first pending row, reads its Google Doc, and
produces SEOPage[]. READ-ONLY: no writeback. Run with:  pytest -m live

Note: the first run performs browser OAuth consent (unless a valid token file
already exists); subsequent runs reuse the cached token.
"""
import os
from pathlib import Path

import pytest

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover
    pass

pytestmark = pytest.mark.live


def _require(name):
    value = (os.getenv(name) or "").strip()
    if not value:
        pytest.skip(f"{name} not configured; skipping live Google test")
    return value


def _require_file(name):
    """Require an env var naming a file AND that the file exists.

    Skips (rather than fails) when the file is not present yet, so the live test
    only runs when it can genuinely authenticate.
    """
    value = _require(name)
    if not Path(value).exists():
        pytest.skip(f"{name}={value!r} does not exist; skipping live Google test")
    return value


def test_sheet_to_doc_to_pages():
    credentials_file = _require_file("ANTLER_GOOGLE_CREDENTIALS_FILE")
    token_file = os.getenv("ANTLER_GOOGLE_TOKEN_FILE", "token.json")
    sheet_url = _require("ANTLER_GOOGLE_SHEET_URL")

    from antler_seo.input.google_auth import load_oauth_credentials
    from antler_seo.input.google_sheet import GoogleSheetReader, build_sheets_service
    from antler_seo.input.google_doc import (
        GoogleDocReader,
        GoogleDocSource,
        build_docs_service,
    )

    creds = load_oauth_credentials(credentials_file, token_file)

    sheet_reader = GoogleSheetReader(build_sheets_service(creds))
    pending = sheet_reader.pending_rows(sheet_url)
    if not pending:
        pytest.skip("No pending rows in the configured Sheet")

    row = next((r for r in pending if r.has_doc_link), None)
    if row is None:
        pytest.skip("No pending row has a Google Doc link")

    doc_reader = GoogleDocReader(build_docs_service(creds))
    source = GoogleDocSource(
        row.doc_link, reader=doc_reader, restaurant_name=row.restaurant_name
    )
    outcome = source.load()

    assert outcome.restaurant_name == row.restaurant_name
    # The doc should parse into at least one page (or report parse errors).
    assert outcome.has_pages or outcome.has_errors


def test_sheet_writeback_to_test_row():
    """Gated write-back round-trip against a DEDICATED TEST ROW.

    Requires explicit opt-in: set ANTLER_GOOGLE_TEST_WRITE_ROW to the 1-based
    Sheet row number of a throwaway TEST row (NEVER the Renovo row). Writes
    temporary values to E:G only, verifies via read-back, then restores the
    original E:G values. Columns A:D are never touched.
    """
    credentials_file = _require_file("ANTLER_GOOGLE_CREDENTIALS_FILE")
    token_file = os.getenv("ANTLER_GOOGLE_TOKEN_FILE", "token.json")
    sheet_url = _require("ANTLER_GOOGLE_SHEET_URL")

    raw_row = (os.getenv("ANTLER_GOOGLE_TEST_WRITE_ROW") or "").strip()
    if not raw_row:
        pytest.skip(
            "ANTLER_GOOGLE_TEST_WRITE_ROW not set; skipping live Sheet write test"
        )
    try:
        test_row = int(raw_row)
    except ValueError:
        pytest.skip(f"ANTLER_GOOGLE_TEST_WRITE_ROW={raw_row!r} is not an integer")
    if test_row < 2:
        pytest.skip("TEST write row must be >= 2 (row 1 is the header)")

    from antler_seo.input.google_auth import load_oauth_credentials
    from antler_seo.input.google_sheet import (
        GoogleSheetReader,
        GoogleSheetWriter,
        build_sheets_service,
    )

    creds = load_oauth_credentials(credentials_file, token_file)
    service = build_sheets_service(creds)
    reader = GoogleSheetReader(service)
    writer = GoogleSheetWriter(service)

    # Safety: never write to the row Renovo occupies.
    for r in reader.read_rows(sheet_url):
        if r.row_number == test_row and r.restaurant_name.strip().lower() == "renovo":
            pytest.skip("Refusing to write: TEST row coincides with the Renovo row")

    original = reader.read_status_cells(sheet_url, test_row)

    marker = "AUTOMATION_TEST"
    try:
        writer.write_status(
            sheet_url,
            test_row,
            completed="No",
            last_run="LIVE-TEST",
            notes=marker,
        )
        after = reader.read_status_cells(sheet_url, test_row)
        assert after == ["No", "LIVE-TEST", marker]
    finally:
        # Restore the original E:G values.
        writer.write_status(
            sheet_url,
            test_row,
            completed=original[0],
            last_run=original[1],
            notes=original[2],
        )
    restored = reader.read_status_cells(sheet_url, test_row)
    assert restored == original
