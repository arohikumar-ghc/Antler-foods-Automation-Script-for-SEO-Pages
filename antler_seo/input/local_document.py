"""
Local structured-document input pipeline (MVP input source).

Parses a plain ``.md`` / ``.txt`` document containing one or more SEO pages,
each delimited by explicit markers::

    === PAGE START ===
    Page Name: Butter Chicken
    Href: /butter-chicken
    SEO Title: Order Butter Chicken Online
    SEO Description: Creamy butter chicken ...
    Social Title: Order Butter Chicken Online        (optional)
    Social Description: Creamy butter chicken ...     (optional)
    Image: 001-butter-chicken.jpg                     (optional)
    Subtitle: Authentic Indian Cuisine
    Title: Butter Chicken
    Description: Our signature butter chicken ...
    FAQ Question 1: Is it spicy?
    FAQ Answer 1: Mild to medium.
    FAQ Question 2: Does it contain nuts?
    FAQ Answer 2: Yes, cashew paste.
    === PAGE END ===

Design notes:
* Fields use explicit labels (``Label: value``) — never positional parsing.
* A field value may continue across following lines; a line that is not a
  recognised ``Label:`` is appended to the current field (so URLs/colons inside
  a Description don't break parsing).
* Multiple FAQs via ``FAQ Question N`` / ``FAQ Answer N`` pairs.
* ``Image`` is captured into :class:`ImageRef` but NO image processing happens
  here (deferred to a later phase).
* Malformed-page isolation: a page block that is missing required fields is
  recorded as an error and skipped; valid pages in the same document are still
  returned.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from antler_seo.models import FAQ, ImageRef, SEOPage
from antler_seo.input.base import (
    InputError,
    InputSource,
    PageParseError,
    ParseOutcome,
)

PAGE_START = "=== PAGE START ==="
PAGE_END = "=== PAGE END ==="

# Canonical known field labels (lowercase -> canonical key).
_SIMPLE_FIELDS = {
    "page name": "page_name",
    "href": "href",
    "seo title": "seo_title",
    "seo description": "seo_description",
    "social title": "social_title",
    "social description": "social_description",
    "image": "image",
    "subtitle": "subtitle",
    "title": "title",
    "description": "description",
}

_REQUIRED_SIMPLE_FIELDS = (
    "page_name",
    "href",
    "seo_title",
    "seo_description",
    "subtitle",
    "title",
    "description",
)

_FAQ_QUESTION_RE = re.compile(r"^faq\s+question\s+(\d+)$", re.IGNORECASE)
_FAQ_ANSWER_RE = re.compile(r"^faq\s+answer\s+(\d+)$", re.IGNORECASE)
_LABEL_RE = re.compile(r"^([^:]+):(.*)$")


class LocalDocumentParseError(Exception):
    """Raised internally when a single page block cannot be parsed."""


class LocalDocumentSource(InputSource):
    """Input source that reads SEO pages from a local structured document."""

    def __init__(self, path: str):
        self.path = Path(path)

    def load(self) -> ParseOutcome:
        if not self.path.exists():
            raise InputError(f"Input document not found: {self.path}")
        if not self.path.is_file():
            raise InputError(f"Input path is not a file: {self.path}")

        try:
            text = self.path.read_text(encoding="utf-8")
        except OSError as exc:
            raise InputError(f"Could not read input document: {exc}") from exc

        return parse_text(text)


def _split_page_blocks(text: str) -> List[str]:
    """Return the raw text of each page block (between START and END)."""
    blocks: List[str] = []
    segments = text.split(PAGE_START)
    # segments[0] is any preamble before the first page; skip it.
    for segment in segments[1:]:
        if PAGE_END in segment:
            block = segment.split(PAGE_END, 1)[0]
        else:
            # No closing delimiter — take the rest; the parser will still
            # validate required fields and report problems.
            block = segment
        blocks.append(block)
    return blocks


def _parse_fields(block: str) -> Tuple[Dict[str, str], Dict[int, Dict[str, str]]]:
    """Parse a page block into (simple fields, faq-by-index).

    faq-by-index maps N -> {"question": ..., "answer": ...}.
    """
    fields: Dict[str, str] = {}
    faqs: Dict[int, Dict[str, str]] = {}
    current_target: Optional[Tuple[str, Optional[int], str]] = None
    # current_target = (kind, index, subkey)
    #   kind "simple": subkey is the canonical field key
    #   kind "faq":    index is N, subkey is "question"/"answer"

    for raw_line in block.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        label_match = _LABEL_RE.match(line)
        recognised = False

        if label_match:
            label = label_match.group(1).strip()
            value = label_match.group(2).strip()
            label_lower = label.lower()

            q_match = _FAQ_QUESTION_RE.match(label_lower)
            a_match = _FAQ_ANSWER_RE.match(label_lower)

            if label_lower in _SIMPLE_FIELDS:
                key = _SIMPLE_FIELDS[label_lower]
                fields[key] = value
                current_target = ("simple", None, key)
                recognised = True
            elif q_match:
                idx = int(q_match.group(1))
                faqs.setdefault(idx, {})["question"] = value
                current_target = ("faq", idx, "question")
                recognised = True
            elif a_match:
                idx = int(a_match.group(1))
                faqs.setdefault(idx, {})["answer"] = value
                current_target = ("faq", idx, "answer")
                recognised = True

        if not recognised:
            # Continuation of the current field (handles colons in values and
            # genuine multi-line values).
            if current_target is None:
                continue
            kind, idx, subkey = current_target
            if kind == "simple":
                existing = fields.get(subkey, "")
                fields[subkey] = (existing + " " + line).strip() if existing else line
            else:
                target = faqs.setdefault(idx, {})
                existing = target.get(subkey, "")
                target[subkey] = (existing + " " + line).strip() if existing else line

    return fields, faqs


def _build_faqs(faqs_by_index: Dict[int, Dict[str, str]]) -> List[FAQ]:
    """Build an ordered FAQ list from the index map.

    Pairs are ordered by N. A pair is included only if it has both a question
    and an answer with content; incomplete pairs are dropped (SEOPage.validate
    then reports if no usable FAQ remains).
    """
    result: List[FAQ] = []
    for idx in sorted(faqs_by_index):
        pair = faqs_by_index[idx]
        question = (pair.get("question") or "").strip()
        answer = (pair.get("answer") or "").strip()
        if question and answer:
            result.append(FAQ(question=question, answer=answer))
    return result


def _parse_block(block: str, index: int) -> SEOPage:
    """Parse a single page block into an SEOPage, or raise on required-field
    problems."""
    fields, faqs_by_index = _parse_fields(block)

    missing = [
        key
        for key in _REQUIRED_SIMPLE_FIELDS
        if not (fields.get(key) or "").strip()
    ]
    if missing:
        raise LocalDocumentParseError(
            "missing required fields: " + ", ".join(missing)
        )

    faqs = _build_faqs(faqs_by_index)
    if not faqs:
        raise LocalDocumentParseError(
            "at least one complete FAQ (question + answer) is required"
        )

    image: Optional[ImageRef] = None
    image_filename = (fields.get("image") or "").strip()
    if image_filename:
        image = ImageRef(filename=image_filename)

    return SEOPage(
        href=fields["href"],
        page_name=fields["page_name"],
        seo_title=fields["seo_title"],
        seo_description=fields["seo_description"],
        subtitle=fields["subtitle"],
        title=fields["title"],
        description=fields["description"],
        faqs=faqs,
        social_title=(fields.get("social_title") or "").strip() or None,
        social_description=(fields.get("social_description") or "").strip()
        or None,
        image=image,
    )


def parse_text(text: str) -> ParseOutcome:
    """Parse a document string into a :class:`ParseOutcome`.

    Malformed page blocks are recorded in ``errors`` and skipped; valid pages
    are returned in ``pages``.
    """
    outcome = ParseOutcome()

    blocks = _split_page_blocks(text)
    for i, block in enumerate(blocks, 1):
        try:
            page = _parse_block(block, i)
            outcome.pages.append(page)
        except LocalDocumentParseError as exc:
            outcome.errors.append(PageParseError(index=i, message=str(exc)))

    return outcome


def parse_file(path: str) -> ParseOutcome:
    """Convenience wrapper around :class:`LocalDocumentSource`."""
    return LocalDocumentSource(path).load()
