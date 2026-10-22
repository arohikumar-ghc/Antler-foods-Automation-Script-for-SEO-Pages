"""Offline tests for the orchestrator (no browser, no network)."""
from antler_seo.input.google_sheet import RestaurantRow
from antler_seo.input.base import ParseOutcome
from antler_seo.input.sheet_pipeline import RowResult, ROW_STATUS_OK
from antler_seo.models import (
    FAQ, PageResult, SEOPage,
    SECTION_BASIC_INFO, SECTION_SEO_METADATA, SECTION_CONTENT, SECTION_FAQ,
)
from antler_seo.orchestrator import (
    content_mismatch_pages, process_restaurant, run_batch,
)


def _row(row_number=2, name="Renovo", doc="https://docs.google.com/document/d/D/edit"):
    return RestaurantRow(
        row_number=row_number, restaurant_name=name, doc_link=doc,
        image_folder="", no_of_pages="", completed="", last_run="", notes="",
    )


def _page(name, href, *, brand="Renovo", body="Renovo great food", faqs=1):
    full_name = f"{name} | {brand}" if brand else name
    return SEOPage(
        href=href, page_name=full_name,
        seo_title=f"{name} | {brand}" if brand else name,
        seo_description=body, subtitle="Sub", title=name, description=body,
        faqs=[FAQ(f"Q{i}?", f"A{i}.") for i in range(1, faqs + 1)],
    )


def _ok_outcome(pages):
    oc = ParseOutcome(pages=list(pages), errors=[], restaurant_name="Renovo")
    return RowResult(
        row_number=2, restaurant_name="Renovo", doc_link="d",
        image_folder_link="", no_of_pages="", status=ROW_STATUS_OK, outcome=oc,
    )


def _err_outcome():
    rr = RowResult(
        row_number=2, restaurant_name="Renovo", doc_link="",
        image_folder_link="", no_of_pages="", status=ROW_STATUS_OK,
    )
    rr.add_error("Google Doc Link is required")  # flips status to error
    return rr


def _all_sections_ok():
    return {
        SECTION_BASIC_INFO: True, SECTION_SEO_METADATA: True,
        SECTION_CONTENT: True, SECTION_FAQ: True,
    }


def _fake_clock(step=5.0):
    """Deterministic monotonic clock: advances `step` seconds per call."""
    state = {"t": 0.0}

    def clock():
        now = state["t"]
        state["t"] += step
        return now

    return clock


class FakeCMS:
    """Records create_seo_page calls; configurable per-href behavior."""

    def __init__(self, existing=None, raise_on=None, partial_on=None,
                 select_raises_on=None):
        self.existing = set(existing or [])
        self.raise_on = set(raise_on or [])
        self.partial_on = set(partial_on or [])
        self.select_raises_on = set(select_raises_on or [])
        self.created = []
        self.selected = []
        self.alive = True  # session-health flag (see is_session_alive)

    def select_restaurant(self, name):
        self.selected.append(name)
        if name in self.select_raises_on:
            raise RuntimeError("select failed for " + name)

    def open_pages(self):
        pass

    def is_session_alive(self):
        return self.alive

    def page_exists(self, page_name, href=""):
        return href in self.existing

    def create_seo_page(self, page, publish=False):
        self.created.append(page.href)
        if page.href in self.raise_on:
            raise RuntimeError("boom " + page.href)
        if page.href in self.existing:
            return PageResult.skipped_result(page.page_name, page.href)
        if page.href in self.partial_on:
            s = _all_sections_ok()
            s[SECTION_FAQ] = False
            return PageResult.from_sections(page.page_name, page.href, s)
        return PageResult.from_sections(page.page_name, page.href, _all_sections_ok())


class FakeWriter:
    def __init__(self):
        self.calls = []

    def write_status(self, sheet_url, row_number, *, completed, last_run, notes):
        self.calls.append({
            "sheet_url": sheet_url, "row_number": row_number,
            "completed": completed, "last_run": last_run, "notes": notes,
        })


# --- content mismatch ------------------------------------------------------


def test_matching_pages_not_flagged():
    pages = [_page("Butter Chicken", "/butter-chicken", brand="Renovo")]
    assert content_mismatch_pages("Renovo", pages) == []


def test_competing_brand_flagged_even_with_generic_overlap():
    pages = [_page("Bharva Kulcha", "/bharva-kulcha", brand="Apna Desi Pizza",
                   body="Delicious pizza in Indianapolis")]
    assert len(content_mismatch_pages("Renovo", pages)) == 1


def test_single_generic_token_does_not_clear_competing_page():
    pages = [_page("Veg Pizza", "/veg-pizza", brand="Apna Desi Pizza",
                   body="pizza pizza pizza")]
    assert len(content_mismatch_pages("Renovo", pages)) == 1


def test_page_without_restaurant_reference_flagged():
    p = SEOPage(href="/x", page_name="Dish", seo_title="Dish", seo_description="d",
                subtitle="s", title="Dish", description="no brand here",
                faqs=[FAQ("q", "a")])
    assert len(content_mismatch_pages("Renovo", [p])) == 1


# --- process_restaurant: happy / isolation / skip --------------------------


def test_all_pages_success_is_complete():
    pages = [_page("A", "/a"), _page("B", "/b")]
    res = process_restaurant(_row(), FakeCMS(), lambda r: _ok_outcome(pages))
    assert res.total == 2 and res.success == 2
    assert res.is_complete


def test_per_page_failure_isolated_blocks_completion():
    pages = [_page("A", "/a"), _page("B", "/b")]
    cms = FakeCMS(raise_on={"/a"})
    res = process_restaurant(_row(), cms, lambda r: _ok_outcome(pages))
    assert res.failed == 1 and res.success == 1
    assert cms.created == ["/a", "/b"]
    assert not res.is_complete


def test_duplicate_page_skipped():
    pages = [_page("A", "/a")]
    cms = FakeCMS(existing={"/a"})
    res = process_restaurant(_row(), cms, lambda r: _ok_outcome(pages))
    assert res.skipped == 1 and res.success == 0
    assert res.is_complete


def test_input_error_not_complete():
    res = process_restaurant(_row(), FakeCMS(), lambda r: _err_outcome())
    assert res.total == 0 and not res.is_complete and not res.reached_processing


# --- max_pages subset guard ------------------------------------------------


def test_max_pages_subset_blocks_completion():
    pages = [_page("A", "/a"), _page("B", "/b"), _page("C", "/c")]
    cms = FakeCMS()
    res = process_restaurant(_row(), cms, lambda r: _ok_outcome(pages), max_pages=1)
    assert cms.created == ["/a"]
    assert res.success == 1
    assert not res.is_complete
    assert any("Partial run" in e for e in res.errors)


def test_max_pages_equal_total_is_allowed_complete():
    pages = [_page("A", "/a"), _page("B", "/b")]
    res = process_restaurant(_row(), FakeCMS(), lambda r: _ok_outcome(pages), max_pages=2)
    assert res.is_complete


# --- content mismatch inside process_restaurant ----------------------------


def test_mismatched_pages_not_created_and_block_completion():
    pages = [_page("Bharva Kulcha", "/bk", brand="Apna Desi Pizza",
                   body="pizza in Indianapolis")]
    cms = FakeCMS()
    res = process_restaurant(_row(), cms, lambda r: _ok_outcome(pages))
    assert cms.created == []
    assert res.failed == 1
    assert not res.is_complete
    assert any("Content mismatch" in e for e in res.errors)


# --- run_batch: isolation + write-back gating ------------------------------


def test_run_batch_writeback_only_when_complete():
    rows = [_row(row_number=2, name="Good"), _row(row_number=3, name="Bad")]
    # Page content references its own restaurant (brand + body) so the
    # content-mismatch safeguard is satisfied; the only difference is the
    # per-page CMS outcome (Bad's page is forced to raise).
    pages_good = [_page("Dish", "/a", brand="Good", body="Good restaurant food")]
    pages_bad = [_page("Dish", "/b", brand="Bad", body="Bad restaurant food")]

    def load_row(r):
        if r.restaurant_name == "Good":
            oc = ParseOutcome(pages=list(pages_good), errors=[], restaurant_name="Good")
        else:
            oc = ParseOutcome(pages=list(pages_bad), errors=[], restaurant_name="Bad")
        return RowResult(
            row_number=r.row_number, restaurant_name=r.restaurant_name,
            doc_link="d", image_folder_link="", no_of_pages="",
            status=ROW_STATUS_OK, outcome=oc,
        )

    cms = FakeCMS(raise_on={"/b"})
    writer = FakeWriter()
    results = run_batch(
        rows, cms, load_row, writer=writer,
        sheet_url="https://docs.google.com/spreadsheets/d/S/edit",
        write_back=True, clock=_fake_clock(),
    )
    assert len(results) == 2
    # Every attempted restaurant is written (complete AND failed).
    assert len(writer.calls) == 2
    by_row = {c["row_number"]: c for c in writer.calls}
    # Good (row 2) is complete -> "1 page created", no INCOMPLETE prefix.
    assert by_row[2]["completed"] == "1 page created"
    assert "INCOMPLETE" not in by_row[2]["completed"]
    assert by_row[2]["last_run"]  # some elapsed string (e.g. "5 sec")
    # Bad (row 3) failed -> INCOMPLETE prefix (keeps the row pending).
    assert by_row[3]["completed"].startswith("INCOMPLETE:")
    assert "created 0" in by_row[3]["notes"] or "INCOMPLETE" in by_row[3]["notes"]


def test_run_batch_no_writeback_when_write_back_false():
    rows = [_row()]
    writer = FakeWriter()
    run_batch(rows, FakeCMS(), lambda r: _ok_outcome([_page("A", "/a")]),
              writer=writer, sheet_url="s", write_back=False)
    assert writer.calls == []


def test_run_batch_restaurant_isolation():
    rows = [_row(row_number=2, name="X"), _row(row_number=3, name="Y")]
    cms = FakeCMS(select_raises_on={"X"})

    def load_row(r):
        # Page content references the row's own restaurant (satisfies the
        # content-mismatch safeguard); X never reaches here because select
        # raises first.
        page = _page("Dish", "/a", brand=r.restaurant_name,
                     body=f"{r.restaurant_name} food")
        oc = ParseOutcome(pages=[page], errors=[],
                          restaurant_name=r.restaurant_name)
        return RowResult(
            row_number=r.row_number, restaurant_name=r.restaurant_name,
            doc_link="d", image_folder_link="", no_of_pages="",
            status=ROW_STATUS_OK, outcome=oc,
        )

    results = run_batch(rows, cms, load_row)
    assert len(results) == 2
    assert not results[0].is_complete                      # X: select raised
    assert any("Unexpected error" in e for e in results[0].errors)
    assert results[1].is_complete                          # Y: processed fine


def test_run_batch_partial_written_as_incomplete():
    # A partial restaurant IS written (per decision), but with an INCOMPLETE
    # prefix so pending-row detection keeps the row pending.
    rows = [_row(row_number=5, name="Renovo")]
    cms = FakeCMS(partial_on={"/a"})
    writer = FakeWriter()
    results = run_batch(rows, cms, lambda r: _ok_outcome([_page("A", "/a")]),
                        writer=writer, sheet_url="s", write_back=True,
                        clock=_fake_clock())
    assert len(writer.calls) == 1
    assert writer.calls[0]["completed"].startswith("INCOMPLETE:")
    assert not results[0].is_complete


def test_run_batch_sets_elapsed_per_restaurant():
    rows = [_row(row_number=2, name="Renovo"), _row(row_number=3, name="Renovo")]
    results = run_batch(rows, FakeCMS(), lambda r: _ok_outcome([_page("A", "/a")]),
                        clock=_fake_clock(step=5.0))
    # Each restaurant timed independently via the injected clock (5s/call).
    for res in results:
        assert res.elapsed_seconds == 5.0


def test_run_batch_session_death_stops_and_marks_remaining():
    rows = [_row(row_number=2, name="X"), _row(row_number=3, name="Y"),
            _row(row_number=4, name="Z")]
    # X raises AND the session reports dead -> stop; Y, Z not processed.
    cms = FakeCMS(select_raises_on={"X"})
    cms.alive = False  # health check returns False after the raise

    results = run_batch(rows, cms, lambda r: _ok_outcome([_page("A", "/a")]))
    assert len(results) == 3
    assert any("Session became unusable" in e for e in results[0].errors)
    assert any("session became unusable earlier" in e for e in results[1].errors)
    assert any("session became unusable earlier" in e for e in results[2].errors)
    # Only X was attempted (select called once).
    assert cms.selected == ["X"]


def test_run_batch_session_dead_not_written():
    rows = [_row(row_number=2, name="X"), _row(row_number=3, name="Y")]
    cms = FakeCMS(select_raises_on={"X"})
    cms.alive = False
    writer = FakeWriter()
    run_batch(rows, cms, lambda r: _ok_outcome([_page("A", "/a")]),
              writer=writer, sheet_url="s", write_back=True, clock=_fake_clock())
    # X attempted (written), Y never attempted (not written).
    assert [c["row_number"] for c in writer.calls] == [2]


def _doc_read_fail_outcome(row_number):
    """RowResult simulating a Doc-read failure (as process_row returns one)."""
    rr = RowResult(
        row_number=row_number, restaurant_name="R", doc_link="d",
        image_folder_link="", no_of_pages="", status=ROW_STATUS_OK,
    )
    rr.add_error("Failed to read Google Doc: WinError 10054")  # -> status error
    return rr


def test_run_batch_doc_read_failure_written_and_next_restaurant_continues():
    rows = [_row(row_number=3, name="Karma"), _row(row_number=4, name="Renovo")]

    def load_row(r):
        if r.restaurant_name == "Karma":
            return _doc_read_fail_outcome(r.row_number)
        return _ok_outcome([_page("A", "/a")])

    cms = FakeCMS()  # session stays alive; a Doc failure must not kill it
    writer = FakeWriter()
    results = run_batch(rows, cms, load_row, writer=writer, sheet_url="s",
                        write_back=True, clock=_fake_clock(step=10.0))

    assert len(results) == 2
    by_row = {c["row_number"]: c for c in writer.calls}
    # Karma (Doc read failed): attempted -> written with INCOMPLETE 0 created,
    # real elapsed, and an error note explaining the Doc read failure.
    assert by_row[3]["completed"] == "INCOMPLETE: 0 pages created"
    assert by_row[3]["last_run"] == "10 sec"
    assert "Failed to read Google Doc" in by_row[3]["notes"]
    # The next restaurant was still processed and written.
    assert by_row[4]["completed"] == "1 page created"
    # Session stayed usable: both restaurants were selected.
    assert cms.selected == ["Karma", "Renovo"]
