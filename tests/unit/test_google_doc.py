"""Unit tests for the Google Doc reader and source (no network)."""
import pytest

from antler_seo.input.base import InputError
from antler_seo.input.google_doc import (
    DocError,
    GoogleDocReader,
    GoogleDocSource,
    document_to_text,
    extract_document_id,
)


def _doc_json(lines):
    """Build a minimal Docs API resource whose paragraphs are the given lines."""
    content = []
    for line in lines:
        content.append(
            {
                "paragraph": {
                    "elements": [
                        {"textRun": {"content": line + "\n"}},
                    ]
                }
            }
        )
    return {"body": {"content": content}}


class FakeDocReader:
    """Reader stand-in returning canned text (or raising)."""

    def __init__(self, text=None, error=None):
        self._text = text
        self._error = error

    def fetch_text(self, url_or_id):
        if self._error is not None:
            raise self._error
        return self._text


PAGE_TEXT = "\n".join(
    [
        "=== PAGE START ===",
        "Page Name: About",
        "Href: /about",
        "SEO Title: About Us",
        "SEO Description: About our restaurant.",
        "Subtitle: Our Story",
        "Title: About",
        "Description: We cook great food.",
        "FAQ Question 1: Where are you?",
        "FAQ Answer 1: Downtown.",
        "=== PAGE END ===",
    ]
)


def test_extract_document_id_from_url():
    url = "https://docs.google.com/document/d/1Doc-_Id123/edit"
    assert extract_document_id(url) == "1Doc-_Id123"


def test_extract_document_id_accepts_bare_id():
    assert extract_document_id("1DocIdABCDEFGHIJKLMNOP") == "1DocIdABCDEFGHIJKLMNOP"


@pytest.mark.parametrize("bad", ["", "   ", "nope", "https://example.com/d/x"])
def test_extract_document_id_invalid(bad):
    with pytest.raises(DocError):
        extract_document_id(bad)


def test_document_to_text_joins_paragraphs():
    doc = _doc_json(["=== PAGE START ===", "Page Name: About", "=== PAGE END ==="])
    text = document_to_text(doc)
    assert text == "=== PAGE START ===\nPage Name: About\n=== PAGE END ==="


def test_document_to_text_empty_body():
    assert document_to_text({}) == ""
    assert document_to_text({"body": {"content": []}}) == ""


def test_source_load_produces_pages_and_restaurant():
    source = GoogleDocSource(
        "https://docs.google.com/document/d/DID/edit",
        reader=FakeDocReader(text=PAGE_TEXT),
        restaurant_name="Renovo",
    )
    outcome = source.load()
    assert outcome.restaurant_name == "Renovo"
    assert len(outcome.pages) == 1
    assert outcome.pages[0].page_name == "About"
    assert outcome.pages[0].href == "/about"


def test_source_restaurant_header_from_doc_when_no_override():
    text = "Restaurant: Palle Ruchi\n\n" + PAGE_TEXT
    source = GoogleDocSource("DID_bare_1234567890xx", reader=FakeDocReader(text=text))
    outcome = source.load()
    assert outcome.restaurant_name == "Palle Ruchi"


def test_source_override_beats_doc_header():
    text = "Restaurant: FromDoc\n\n" + PAGE_TEXT
    source = GoogleDocSource(
        "DID_bare_1234567890xx",
        reader=FakeDocReader(text=text),
        restaurant_name="FromOverride",
    )
    outcome = source.load()
    assert outcome.restaurant_name == "FromOverride"


def test_source_malformed_doc_isolates_errors():
    bad = "\n".join(
        ["=== PAGE START ===", "Page Name: Broken", "SEO Title: X", "=== PAGE END ==="]
    )
    source = GoogleDocSource("DID_bare_1234567890xx", reader=FakeDocReader(text=bad))
    outcome = source.load()
    assert outcome.pages == []
    assert len(outcome.errors) == 1


def test_source_empty_text_no_pages():
    source = GoogleDocSource("DID_bare_1234567890xx", reader=FakeDocReader(text=""))
    outcome = source.load()
    assert outcome.pages == []
    assert outcome.errors == []


def test_source_doc_error_propagates():
    source = GoogleDocSource(
        "DID_bare_1234567890xx", reader=FakeDocReader(error=DocError("boom"))
    )
    with pytest.raises(DocError):
        source.load()


def test_source_unexpected_error_wrapped_as_input_error():
    source = GoogleDocSource(
        "DID_bare_1234567890xx", reader=FakeDocReader(error=RuntimeError("net"))
    )
    with pytest.raises(InputError):
        source.load()


# --- GoogleDocReader bounded retry (transient connection failures) ---------


class _FakeDocsService:
    """Fake Docs service: documents().get(...).execute() runs a scripted
    sequence of behaviors (exception instances raise; dicts return)."""

    def __init__(self, behaviors):
        self._behaviors = list(behaviors)
        self.calls = 0

    def documents(self):
        return self

    def get(self, documentId):  # noqa: N803 (match API signature)
        self._doc_id = documentId
        return self

    def execute(self):
        behavior = self._behaviors[self.calls]
        self.calls += 1
        if isinstance(behavior, Exception):
            raise behavior
        return behavior


_GOOD_DOC = _doc_json(
    ["=== PAGE START ===", "Page Name: A", "=== PAGE END ==="]
)


def _reset(msg="forcibly closed"):
    # ConnectionResetError is how WinError 10054 surfaces in Python.
    return ConnectionResetError(10054, msg)


def test_fetch_text_retries_then_succeeds():
    svc = _FakeDocsService([_reset(), _reset(), _GOOD_DOC])
    reader = GoogleDocReader(svc, max_attempts=4, base_delay=0, sleeper=lambda s: None)
    text = reader.fetch_text("DID_bare_1234567890xx")
    assert "=== PAGE START ===" in text
    assert svc.calls == 3  # two failures + one success


def test_fetch_text_gives_up_after_max_attempts():
    svc = _FakeDocsService([_reset(), _reset(), _reset(), _reset()])
    reader = GoogleDocReader(svc, max_attempts=4, base_delay=0, sleeper=lambda s: None)
    with pytest.raises(DocError) as exc:
        reader.fetch_text("DID_bare_1234567890xx")
    assert svc.calls == 4  # bounded: exactly max_attempts
    assert "after 4 attempt" in str(exc.value)


def test_fetch_text_non_transient_not_retried():
    # A non-OSError (e.g. permission/404-style) must not be retried.
    svc = _FakeDocsService([ValueError("not found"), _GOOD_DOC])
    reader = GoogleDocReader(svc, max_attempts=4, base_delay=0, sleeper=lambda s: None)
    with pytest.raises(DocError):
        reader.fetch_text("DID_bare_1234567890xx")
    assert svc.calls == 1  # no retry on non-transient error


def test_fetch_text_backoff_is_bounded_and_sleeps_between_attempts():
    delays = []
    svc = _FakeDocsService([_reset(), _reset(), _GOOD_DOC])
    reader = GoogleDocReader(
        svc, max_attempts=4, base_delay=1.0, backoff_factor=2.0,
        sleeper=lambda s: delays.append(s),
    )
    reader.fetch_text("DID_bare_1234567890xx")
    assert delays == [1.0, 2.0]  # exponential backoff, one sleep per retry
