"""
Orchestration: Google Sheet → Google Doc → parse → validate → Antler CMS →
(optional) Google Sheet status write-back.

Connects the existing components; it adds no parsing, auth, or CMS logic of its
own:
  * input: :func:`antler_seo.input.sheet_pipeline.process_row` (Doc fetch-once +
    parse + validate + restaurant-name authority + No.-of-Pages enforcement),
  * CMS: :class:`antler_seo.automation.antler_cms.AntlerCMS`
    (select_restaurant / open_pages / page_exists / create_seo_page),
  * results: :class:`antler_seo.reporting.RestaurantResult`,
  * write-back: :class:`antler_seo.input.google_sheet.GoogleSheetWriter`
    (columns E:G only), gated on :meth:`RestaurantResult.is_complete`.

Safety defaults: ``publish=False`` and ``write_back=False`` so nothing is
published and nothing is written to the Sheet unless a caller explicitly opts
in. Google Docs remain read-only. Failure isolation is enforced per page and
per restaurant.
"""
from __future__ import annotations

import re
import time
from typing import Callable, List, Optional

from antler_seo.config import Config
from antler_seo.input.google_sheet import RestaurantRow
from antler_seo.input.sheet_pipeline import RowResult, process_row
from antler_seo.logging_setup import get_logger
from antler_seo.models import PageResult, SEOPage
from antler_seo.reporting import RestaurantResult

logger = get_logger("orchestrator")

# A load_row callable turns a RestaurantRow into a RowResult (Doc → parse →
# validate). Injectable so tests pass a fake with no network.
LoadRowFn = Callable[[RestaurantRow], RowResult]

_WORD_RE = re.compile(r"[a-z0-9]+")

# Generic food/location/ordering words that must NOT, on their own, establish
# that a page's content belongs to the selected restaurant.
_GENERIC_TOKENS = frozenset({
    "the", "and", "in", "of", "a", "an", "to", "for", "with", "on", "at",
    "by", "restaurant", "restaurants", "cafe", "kitchen", "grill", "bar",
    "pizza", "pizzas", "indian", "food", "foods", "cuisine", "eatery",
    "truck", "desi", "street", "snacks", "online", "order", "ordering",
    "delivery", "takeout", "pickup", "menu", "near", "me", "best", "fresh",
})


def _tokens(text: str) -> set:
    return set(_WORD_RE.findall((text or "").lower()))


def _distinctive(name: str) -> set:
    """Distinctive tokens of a name: >2 chars and not a generic word."""
    return {t for t in _tokens(name) if len(t) > 2 and t not in _GENERIC_TOKENS}


def _page_text(page: SEOPage) -> str:
    parts = [
        page.page_name, page.seo_title, page.seo_description,
        page.subtitle, page.title, page.description,
    ]
    for faq in page.faqs:
        parts.append(faq.question)
        parts.append(faq.answer)
    return " ".join(p for p in parts if p)


def _trailing_brand(page: SEOPage) -> str:
    """Return a trailing "| Brand" attribution from the name/title, if any.

    Docs often title pages like "Dish in City, ST | Brand Name"; the brand
    after the final pipe identifies the content's true owner.
    """
    for field in (page.page_name, page.seo_title):
        if field and "|" in field:
            return field.rsplit("|", 1)[1].strip()
    return ""


def content_mismatch_pages(
    restaurant_name: str, pages: List[SEOPage]
) -> List[SEOPage]:
    """Return pages whose content does not credibly belong to the restaurant.

    Rules (a single generic token overlap is NOT enough to clear a page):
      (a) Competing brand: a trailing "| Brand" whose *distinctive* tokens are
          disjoint from the restaurant's distinctive tokens → mismatch, even if
          generic words (e.g. "pizza") overlap.
      (b) Otherwise, the restaurant's distinctive tokens must appear somewhere
          in the page text; if none do → mismatch.
      (c) If the restaurant name has no distinctive tokens (fully generic),
          require the full name as a substring; else flag for review (mismatch).
    """
    rest_distinct = _distinctive(restaurant_name)
    mismatched: List[SEOPage] = []
    for page in pages:
        brand_distinct = _distinctive(_trailing_brand(page))
        # (a) explicit competing brand
        if brand_distinct and rest_distinct and brand_distinct.isdisjoint(
            rest_distinct
        ):
            mismatched.append(page)
            continue
        if rest_distinct:
            # (b) require a distinctive restaurant reference
            if rest_distinct.isdisjoint(_tokens(_page_text(page))):
                mismatched.append(page)
        else:
            # (c) fully generic restaurant name — require the full name text
            if restaurant_name.strip().lower() not in _page_text(page).lower():
                mismatched.append(page)
    return mismatched


def process_restaurant(
    row: RestaurantRow,
    cms,
    load_row: LoadRowFn,
    *,
    publish: bool = False,
    max_pages: Optional[int] = None,
    allow_content_mismatch: bool = False,
) -> RestaurantResult:
    """Process one restaurant: load its Doc, then create its SEO pages.

    The caller is expected to have already selected the restaurant and opened
    its Pages screen in the CMS. Page-level failures are isolated — one bad page
    never stops the others. A ``max_pages`` subset run can never be marked
    Completed (it records a restaurant-level error).
    """
    result = RestaurantResult(
        restaurant_name=row.restaurant_name,
        row_number=row.row_number,
        source_doc=row.doc_link,
    )

    # --- Input stage (reuses the existing pipeline) ---
    outcome = load_row(row)
    for err in outcome.errors:
        result.add_error(err)
    for warn in outcome.warnings:
        result.add_warning(warn)

    pages = outcome.outcome.pages if outcome.outcome else []

    # Single clear pre-processing failure path: any input error, or no pages.
    if outcome.status == "error" or not pages:
        logger.warning(
            "Restaurant %s: input stage did not yield processable pages "
            "(status=%s, pages=%d); not reaching page processing.",
            row.restaurant_name, outcome.status, len(pages),
        )
        return result  # reached_processing stays False -> not complete

    total_pages = len(pages)

    # A capped (subset) run must never be eligible for Completed.
    if max_pages is not None and max_pages < total_pages:
        result.add_error(
            f"Partial run: processing {max_pages} of {total_pages} required "
            f"page(s) (max_pages); not eligible for Completed."
        )
        logger.warning("Restaurant %s: subset run %d/%d — will not be Completed.",
                       row.restaurant_name, max_pages, total_pages)

    # --- Content-mismatch safeguard ---
    mismatched = content_mismatch_pages(row.restaurant_name, pages)
    mismatched_hrefs = {p.href for p in mismatched}
    if mismatched and not allow_content_mismatch:
        names = ", ".join(f"{p.page_name} ({p.href})" for p in mismatched)
        # A restaurant-level error guarantees is_complete == False.
        result.add_error(
            f"Content mismatch: {len(mismatched)} page(s) do not reference "
            f"restaurant {row.restaurant_name!r}: {names}. Not created."
        )
        logger.warning("Restaurant %s: content mismatch on %d page(s): %s",
                       row.restaurant_name, len(mismatched), names)

    result.reached_processing = True

    to_process = pages if max_pages is None else pages[:max_pages]
    for page in to_process:
        # Mismatched pages are recorded as failed and NOT created.
        if page.href in mismatched_hrefs and not allow_content_mismatch:
            result.add_page(PageResult.failed_result(
                page.page_name, page.href,
                error="content does not reference the restaurant; not created",
            ))
            continue
        try:
            page_result = cms.create_seo_page(page, publish=publish)
        except Exception as exc:  # isolate per-page failures
            logger.error("Page %s raised: %s", page.page_name, exc)
            page_result = PageResult.failed_result(
                page.page_name, page.href, error=f"Unexpected error: {exc}"
            )
        result.add_page(page_result)

    logger.info(
        "Restaurant %s processed: total=%d success=%d partial=%d failed=%d "
        "skipped=%d complete=%s",
        row.restaurant_name, result.total, result.success, result.partial,
        result.failed, result.skipped, result.is_complete,
    )
    return result


def run_batch(
    rows: List[RestaurantRow],
    cms,
    load_row: LoadRowFn,
    *,
    writer=None,
    sheet_url: Optional[str] = None,
    publish: bool = False,
    write_back: bool = False,
    max_pages: Optional[int] = None,
    allow_content_mismatch: bool = False,
    throttle: Callable[[], None] = lambda: None,
    clock: Callable[[], float] = time.monotonic,
) -> List[RestaurantResult]:
    """Process many restaurants in ONE session with per-restaurant isolation,
    per-restaurant timing, and optional write-back.

    The caller logs in once before calling this; restaurants are processed in
    the same browser session (no re-login between them). One restaurant failing
    never stops the others — unless the session itself becomes unusable (page
    closed or bounced to ``/login``), in which case the batch stops safely and
    remaining restaurants are recorded as not processed. No re-login is ever
    attempted.

    When ``write_back`` is enabled (and ``writer``/``sheet_url`` are supplied),
    every ATTEMPTED restaurant is written to E:G: the created-page count (E,
    prefixed ``INCOMPLETE:`` for non-complete runs so the row stays pending),
    elapsed time (F) and a notes summary (G). Restaurants never attempted
    (session died earlier) are NOT written.
    """
    results: List[RestaurantResult] = []
    session_dead = False

    def _session_alive() -> bool:
        """Health check that never raises; unknown health => assume usable."""
        check = getattr(cms, "is_session_alive", None)
        if not callable(check):
            return True
        try:
            return bool(check())
        except Exception as hc_exc:  # pragma: no cover - defensive
            logger.warning("Session health check raised: %s", hc_exc)
            return False

    for i, row in enumerate(rows):
        if session_dead:
            r = RestaurantResult(
                restaurant_name=row.restaurant_name,
                row_number=row.row_number,
                source_doc=row.doc_link,
            )
            r.add_error("Not processed: browser session became unusable earlier")
            results.append(r)
            continue  # never written to the Sheet (not attempted)

        start = clock()
        try:
            cms.select_restaurant(row.restaurant_name)
            cms.open_pages()
            result = process_restaurant(
                row, cms, load_row,
                publish=publish, max_pages=max_pages,
                allow_content_mismatch=allow_content_mismatch,
            )
        except Exception as exc:  # isolate per-restaurant failures
            logger.error("Restaurant %s raised: %s", row.restaurant_name, exc)
            result = RestaurantResult(
                restaurant_name=row.restaurant_name,
                row_number=row.row_number,
                source_doc=row.doc_link,
            )
            result.add_error(f"Unexpected error: {exc}")
            # Health is decided AFTER recording the real exception, so a
            # health-check failure can never mask `exc`.
            if not _session_alive():
                session_dead = True
                result.add_error("Session became unusable; stopping batch")

        result.elapsed_seconds = clock() - start
        results.append(result)

        # Write-back for every ATTEMPTED restaurant (complete/partial/failed).
        # completed_cell() prefixes "INCOMPLETE:" when not complete, so a
        # partial/failed row stays pending; no "Yes"/false success is written.
        if write_back and writer is not None and sheet_url:
            try:
                writer.write_status(
                    sheet_url,
                    row.row_number,
                    completed=result.completed_cell(),
                    last_run=result.elapsed_cell(),
                    notes=result.notes(),
                )
                logger.info("Wrote status for %s (row %d): %s",
                            row.restaurant_name, row.row_number,
                            result.completed_cell())
            except Exception as exc:  # a write failure must not abort batch
                logger.error("Write-back failed for %s: %s",
                             row.restaurant_name, exc)
                result.add_warning(f"Write-back failed: {exc}")

        # Also detect a session that went bad WITHOUT raising, so we don't
        # continue blindly to the next restaurant. Conservative; no re-login.
        if not session_dead and not _session_alive():
            session_dead = True
            result.add_warning(
                "Session no longer usable after this restaurant; stopping batch"
            )

        if i < len(rows) - 1 and not session_dead:
            throttle()

    return results


def run_from_config(
    config: Config,
    *,
    publish: bool = False,
    write_back: bool = False,
    max_pages: Optional[int] = None,
    restaurants: Optional[List[str]] = None,
    allow_content_mismatch: bool = False,
) -> List[RestaurantResult]:
    """Wire the real components and run the batch.

    SAFETY: ``publish`` and ``write_back`` default to False, so calling this
    neither publishes pages nor writes to the Sheet unless explicitly enabled.
    ``restaurants`` optionally restricts to specific names (e.g. a single
    controlled live test). Lazy imports keep the non-live test suite light.
    """
    from antler_seo.automation.browser import BrowserSession
    from antler_seo.automation.antler_cms import AntlerCMS
    from antler_seo.input.google_auth import load_oauth_credentials
    from antler_seo.input.google_sheet import (
        GoogleSheetReader,
        GoogleSheetWriter,
        build_sheets_service,
    )
    from antler_seo.input.google_doc import GoogleDocReader, build_docs_service

    if not config.google_sheet_url:
        raise ValueError("google_sheet_url is required to run the batch")

    creds = load_oauth_credentials(
        config.google_credentials_file, config.google_token_file
    )
    sheet_reader = GoogleSheetReader(build_sheets_service(creds))
    doc_reader = GoogleDocReader(build_docs_service(creds))
    writer = GoogleSheetWriter(build_sheets_service(creds)) if write_back else None

    rows = sheet_reader.pending_rows(config.google_sheet_url)
    if restaurants:
        wanted = {r.strip().lower() for r in restaurants}
        rows = [r for r in rows if r.restaurant_name.strip().lower() in wanted]

    def load_row(row: RestaurantRow) -> RowResult:
        return process_row(row, lambda: doc_reader, validate=True)

    with BrowserSession(config) as session:
        cms = AntlerCMS(session.page, config)
        cms.login()
        return run_batch(
            rows, cms, load_row,
            writer=writer,
            sheet_url=config.google_sheet_url,
            publish=publish,
            write_back=write_back,
            max_pages=max_pages,
            allow_content_mismatch=allow_content_mismatch,
        )
