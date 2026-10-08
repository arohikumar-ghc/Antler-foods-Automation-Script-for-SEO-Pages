"""
Input source interface.

Every input pipeline implements :class:`InputSource` and returns the same
``List[SEOPage]``, so additional sources (e.g. a future Google Sheet/Doc/Drive
pipeline) can be added without forking the model or the orchestrator.

Parsing results are returned as a :class:`ParseOutcome` so a document with a mix
of valid and malformed pages surfaces both the usable pages and the per-page
errors — one bad page must never silently corrupt the valid ones.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional

from antler_seo.models import SEOPage


class InputError(Exception):
    """Raised when an input source cannot be read at all (e.g. missing file)."""


@dataclass
class PageParseError:
    """A single page that failed to parse, with context for reporting."""

    index: int  # 1-based position of the page block in the document
    message: str


@dataclass
class ParseOutcome:
    """Result of parsing an input document.

    Restaurant/tenant context lives here (batch level), NOT on individual
    ``SEOPage`` objects: every page in one input document belongs to the same
    restaurant, and the automation selects that restaurant once per run. The
    restaurant name is carried dynamically from the input source — never
    hard-coded in the automation.

    Attributes:
        pages: Successfully parsed pages (malformed pages excluded).
        errors: One entry per page block that failed to parse.
        restaurant_name: The restaurant/tenant these pages belong to. ``None``
            if the input did not declare one (the caller must then supply it).
    """

    pages: List[SEOPage] = field(default_factory=list)
    errors: List[PageParseError] = field(default_factory=list)
    restaurant_name: Optional[str] = None

    @property
    def has_pages(self) -> bool:
        return bool(self.pages)

    @property
    def has_errors(self) -> bool:
        return bool(self.errors)

    @property
    def has_restaurant(self) -> bool:
        return bool(self.restaurant_name and self.restaurant_name.strip())


class InputSource(ABC):
    """Abstract input source producing SEO pages."""

    @abstractmethod
    def load(self) -> ParseOutcome:
        """Load and parse the source into a :class:`ParseOutcome`.

        Raises:
            InputError: If the source itself cannot be read.
        """
        raise NotImplementedError
