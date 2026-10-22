"""
Google Doc reader and input source.

A restaurant's SEO pages are authored in a Google Doc using the SAME structured
delimiter format as the local ``.md``/``.txt`` source::

    === PAGE START ===
    Page Name: ...
    Href: ...
    ...
    === PAGE END ===

This module converts a Google Doc into that plain delimiter text and feeds it to
the EXISTING parser (:func:`antler_seo.input.local_document.parse_text`). There
is only one SEOPage parser — the Google layer produces text, nothing more.

Architecture::

    Google Doc -> GoogleDocSource -> parse_text() -> ParseOutcome -> SEOPage[]

Google libraries are imported lazily; :func:`document_to_text` is pure and
unit-testable against fixture document JSON.
"""
from __future__ import annotations

import re
import time
from typing import Optional

from antler_seo.input.base import InputError, InputSource, ParseOutcome
from antler_seo.input.local_document import parse_text
from antler_seo.logging_setup import get_logger

logger = get_logger("input.google_doc")

_DOCUMENT_ID_RE = re.compile(r"/document/d/([a-zA-Z0-9-_]+)")
_BARE_ID_RE = re.compile(r"^[a-zA-Z0-9-_]{20,}$")


class DocError(Exception):
    """Raised when a Google Doc cannot be addressed or read."""


def extract_document_id(url_or_id: str) -> str:
    """Extract a document id from a full URL or accept a bare id.

    Raises:
        DocError: If no id can be determined.
    """
    value = (url_or_id or "").strip()
    if not value:
        raise DocError("Empty document URL/id")

    match = _DOCUMENT_ID_RE.search(value)
    if match:
        return match.group(1)
    if _BARE_ID_RE.match(value):
        return value
    raise DocError(f"Could not extract document id from: {url_or_id!r}")


def document_to_text(doc_json: dict) -> str:
    """Convert a Google Docs API document resource into plain text.

    Walks the document body, concatenating the text runs of each paragraph and
    emitting one newline per paragraph. Tables/other structural elements are
    ignored (the SEO format is line-oriented text). Pure — no network.

    Args:
        doc_json: The ``documents.get`` response resource.

    Returns:
        Plain text suitable for :func:`parse_text`.
    """
    body = (doc_json or {}).get("body", {})
    content = body.get("content", [])
    lines: list[str] = []

    for element in content:
        paragraph = element.get("paragraph")
        if not paragraph:
            continue
        parts: list[str] = []
        for pe in paragraph.get("elements", []):
            text_run = pe.get("textRun")
            if text_run and "content" in text_run:
                parts.append(text_run["content"])
        # textRun content usually ends with its own newline; join then strip the
        # trailing newline so we control line breaks ourselves.
        line = "".join(parts).replace("\r\n", "\n").replace("\r", "\n")
        line = line.rstrip("\n")
        lines.append(line)

    return "\n".join(lines)


# Transient connection errors worth retrying. WinError 10054 ("An existing
# connection was forcibly closed by the remote host") surfaces as
# ConnectionResetError, a subclass of ConnectionError/OSError. HttpError
# (404/permission) is NOT an OSError, so it is never retried here.
_TRANSIENT_ERRORS = (ConnectionError, TimeoutError, OSError)


class GoogleDocReader:
    """Fetches a Google Doc's text via a Google Docs service.

    Transient connection failures (e.g. WinError 10054) are retried a bounded
    number of times with exponential backoff; a fresh request is built on each
    attempt. Non-transient errors (bad id, permission, 404) are not retried.

    Args:
        service: A Google Docs API service (from :func:`build_docs_service`).
        max_attempts: Maximum fetch attempts (>= 1).
        base_delay: Delay before the first retry, in seconds.
        backoff_factor: Multiplier applied to the delay after each failure.
        sleeper: Sleep function (injectable so tests run instantly).
    """

    def __init__(self, service, *, max_attempts: int = 4, base_delay: float = 1.0,
                 backoff_factor: float = 2.0, sleeper=time.sleep):
        self.service = service
        self.max_attempts = max(1, int(max_attempts))
        self.base_delay = base_delay
        self.backoff_factor = backoff_factor
        self._sleeper = sleeper

    def fetch_text(self, url_or_id: str) -> str:
        """Fetch a document and return it as plain delimiter text (with retry).

        Raises:
            DocError: On a non-transient error, or after exhausting retries for
                transient connection failures.
        """
        document_id = extract_document_id(url_or_id)
        logger.info("Fetching Google Doc %s", document_id)

        delay = self.base_delay
        last_exc = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                # Build a fresh request each attempt so a reset connection is
                # retried cleanly.
                doc_json = (
                    self.service.documents().get(documentId=document_id).execute()
                )
                return document_to_text(doc_json)
            except _TRANSIENT_ERRORS as exc:
                last_exc = exc
                if attempt < self.max_attempts:
                    logger.warning(
                        "Transient error reading Doc %s (attempt %d/%d): %r; "
                        "retrying in %.1fs",
                        document_id, attempt, self.max_attempts, exc, delay,
                    )
                    if delay > 0:
                        self._sleeper(delay)
                    delay *= self.backoff_factor
                else:
                    logger.error(
                        "Giving up reading Doc %s after %d attempt(s)",
                        document_id, self.max_attempts,
                    )
            except Exception as exc:
                # Non-transient (e.g. HttpError 404 / permission) — do not retry.
                raise DocError(
                    f"Failed to read Google Doc {document_id}: {exc}"
                ) from exc

        raise DocError(
            f"Failed to read Google Doc {document_id} after "
            f"{self.max_attempts} attempt(s): {last_exc}"
        ) from last_exc


def build_docs_service(credentials):
    """Build a Google Docs API service from credentials (lazy import)."""
    try:
        from googleapiclient.discovery import build  # type: ignore
    except Exception as exc:  # pragma: no cover - exercised when lib absent
        raise DocError(
            "Google API client is not installed. Install it with "
            "`pip install -r requirements.txt`."
        ) from exc
    return build("docs", "v1", credentials=credentials, cache_discovery=False)


class GoogleDocSource(InputSource):
    """Input source that reads SEO pages from a Google Doc.

    Peer of :class:`antler_seo.input.local_document.LocalDocumentSource`; both
    return a :class:`ParseOutcome` so the rest of the system is source-agnostic.

    Args:
        url_or_id: Google Doc URL or document id.
        reader: An object with ``fetch_text(url_or_id) -> str`` (a
            :class:`GoogleDocReader`, or any fake in tests).
        restaurant_name: Optional explicit restaurant/tenant override. When
            provided it takes precedence over any ``Restaurant:`` header in the
            document (the batch driver supplies the Sheet's restaurant name
            here).
    """

    def __init__(self, url_or_id: str, reader, restaurant_name: Optional[str] = None):
        self.url_or_id = url_or_id
        self.reader = reader
        self.restaurant_name = restaurant_name

    def load(self) -> ParseOutcome:
        try:
            text = self.reader.fetch_text(self.url_or_id)
        except DocError:
            raise
        except Exception as exc:
            raise InputError(f"Could not read Google Doc: {exc}") from exc

        outcome = parse_text(text)
        if self.restaurant_name and self.restaurant_name.strip():
            outcome.restaurant_name = self.restaurant_name.strip()
        return outcome
