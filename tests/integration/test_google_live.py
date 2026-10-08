"""Live integration test for the Google cloud input layer.

Gated: auto-skips unless a service-account key and a sheet URL are configured
(ANTLER_GOOGLE_SA_KEY_FILE + ANTLER_GOOGLE_SHEET_URL, loaded from .env). Reads
the real Sheet, finds the first pending row, reads its Google Doc, and produces
SEOPage[]. READ-ONLY: no writeback. Run with:  pytest -m live
"""
import os

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


def test_sheet_to_doc_to_pages():
    key_file = _require("ANTLER_GOOGLE_SA_KEY_FILE")
    sheet_url = _require("ANTLER_GOOGLE_SHEET_URL")

    from antler_seo.input.google_auth import load_service_account_credentials
    from antler_seo.input.google_sheet import GoogleSheetReader, build_sheets_service
    from antler_seo.input.google_doc import (
        GoogleDocReader,
        GoogleDocSource,
        build_docs_service,
    )

    creds = load_service_account_credentials(key_file)

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
