"""
Data models for the Antler Foods SEO automation.

These models are the universal contract between the input/parsing layer, the
validation layer and (later) the browser-automation layer. They are completely
independent of the Antler UI.

Models
------
* :class:`FAQ`        — a single question/answer pair.
* :class:`ImageRef`   — optional hero-image reference. The schema is defined now
                        so enabling images later is additive; image *processing*
                        is NOT implemented in this phase.
* :class:`SEOPage`    — one SEO page's content.
* :class:`PageResult` — per-page run outcome, derived from an explicit map of
                        section successes so every status branch is reachable.
* :class:`BatchResult`— aggregate run outcome across many pages.

Status model
------------
A page's status is one of ``success`` / ``partial`` / ``failed`` / ``skipped``:
* ``skipped``  — the page already existed and was not (re)created.
* ``success``  — every attempted section succeeded.
* ``failed``   — at least one *critical* section failed.
* ``partial``  — all critical sections succeeded but one or more *optional*
                 sections failed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


# --- Status constants ------------------------------------------------------

STATUS_SUCCESS = "success"
STATUS_PARTIAL = "partial"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"

VALID_STATUSES = frozenset(
    {STATUS_SUCCESS, STATUS_PARTIAL, STATUS_FAILED, STATUS_SKIPPED}
)

# --- Section names ---------------------------------------------------------
# The sections an SEO page is built from. "critical" sections must succeed for
# the page to count as anything better than failed.

SECTION_BASIC_INFO = "basic_info"
SECTION_SEO_METADATA = "seo_metadata"
SECTION_SOCIAL_METADATA = "social_metadata"
SECTION_CONTENT = "content"
SECTION_FAQ = "faq"

CRITICAL_SECTIONS = frozenset({SECTION_BASIC_INFO, SECTION_SEO_METADATA})
OPTIONAL_SECTIONS = frozenset(
    {SECTION_SOCIAL_METADATA, SECTION_CONTENT, SECTION_FAQ}
)
ALL_SECTIONS = CRITICAL_SECTIONS | OPTIONAL_SECTIONS


def normalize_href(href: str) -> str:
    """Normalize an href to a leading-slash slug.

    Trims surrounding whitespace and ensures a single leading ``/``. Does not
    otherwise rewrite the slug (case/space rules are enforced by validation so
    the author gets explicit feedback rather than silent mangling).
    """
    if href is None:
        return ""
    cleaned = href.strip()
    if not cleaned:
        return ""
    if not cleaned.startswith("/"):
        cleaned = "/" + cleaned
    return cleaned


# --- FAQ -------------------------------------------------------------------


@dataclass
class FAQ:
    """A single FAQ question/answer pair."""

    question: str
    answer: str

    def validate(self) -> List[str]:
        """Return a list of problems with this FAQ (empty if valid)."""
        errors: List[str] = []
        if not (self.question or "").strip():
            errors.append("FAQ question is empty")
        if not (self.answer or "").strip():
            errors.append("FAQ answer is empty")
        return errors

    def is_valid(self) -> bool:
        return not self.validate()


# --- ImageRef --------------------------------------------------------------


@dataclass
class ImageRef:
    """Optional hero-image reference.

    ``filename`` is the name as written in the source document. ``local_path``
    is resolved later (image phase); it stays ``None`` until then. No image
    processing happens in this phase.
    """

    filename: str
    local_path: Optional[str] = None

    def is_resolved(self) -> bool:
        return bool(self.local_path)


# --- SEOPage ---------------------------------------------------------------


@dataclass
class SEOPage:
    """One SEO page's content.

    Required: ``href``, ``page_name``, ``seo_title``, ``seo_description``,
    ``subtitle``, ``title``, ``description`` and at least one FAQ.
    Optional: ``social_title``, ``social_description``, ``image``.
    """

    href: str
    page_name: str
    seo_title: str
    seo_description: str
    subtitle: str
    title: str
    description: str
    faqs: List[FAQ] = field(default_factory=list)
    social_title: Optional[str] = None
    social_description: Optional[str] = None
    image: Optional[ImageRef] = None

    def __post_init__(self) -> None:
        self.href = normalize_href(self.href)

    # -- social fallback (explicit, never silent) --

    def effective_social_title(self) -> str:
        """Social title to use, falling back to the SEO title if unset."""
        if self.social_title and self.social_title.strip():
            return self.social_title
        return self.seo_title

    def effective_social_description(self) -> str:
        """Social description to use, falling back to the SEO description."""
        if self.social_description and self.social_description.strip():
            return self.social_description
        return self.seo_description

    def social_title_is_fallback(self) -> bool:
        return not (self.social_title and self.social_title.strip())

    def social_description_is_fallback(self) -> bool:
        return not (self.social_description and self.social_description.strip())

    # -- validation --

    def validate(self) -> List[str]:
        """Return a list of validation errors for required fields/rules.

        href *format* rules (case, spaces) are checked by the validation layer
        so authors get explicit feedback; here we only require presence and a
        leading slash.
        """
        errors: List[str] = []

        required_text = {
            "href": self.href,
            "page_name": self.page_name,
            "seo_title": self.seo_title,
            "seo_description": self.seo_description,
            "subtitle": self.subtitle,
            "title": self.title,
            "description": self.description,
        }
        for name, value in required_text.items():
            if not (value or "").strip():
                errors.append(f"{name} is required")

        if self.href and not self.href.startswith("/"):
            errors.append("href must start with '/'")

        if not self.faqs:
            errors.append("at least one FAQ is required")
        else:
            for i, faq in enumerate(self.faqs, 1):
                for problem in faq.validate():
                    errors.append(f"FAQ {i}: {problem}")

        return errors

    def is_valid(self) -> bool:
        return not self.validate()


# --- PageResult ------------------------------------------------------------


@dataclass
class PageResult:
    """Per-page run outcome.

    Prefer the :meth:`from_sections`, :meth:`skipped_result` and
    :meth:`failed_result` constructors so the ``status`` always reflects the
    explicit section map.
    """

    page_name: str
    href: str
    status: str
    sections: Dict[str, bool] = field(default_factory=dict)
    error: Optional[str] = None
    screenshot_path: Optional[str] = None

    def __post_init__(self) -> None:
        if self.status not in VALID_STATUSES:
            raise ValueError(
                f"Invalid status {self.status!r}; expected one of "
                f"{sorted(VALID_STATUSES)}"
            )

    @staticmethod
    def compute_status(
        sections: Dict[str, bool],
        critical: frozenset = CRITICAL_SECTIONS,
    ) -> str:
        """Compute a page status from a section-success map.

        Branches (all reachable):
          * no sections attempted              -> ``failed``
          * any critical section is False      -> ``failed``
          * all attempted sections are True    -> ``success``
          * criticals ok but an optional False -> ``partial``
        """
        if not sections:
            return STATUS_FAILED

        for name in critical:
            if name in sections and not sections[name]:
                return STATUS_FAILED

        if all(sections.values()):
            return STATUS_SUCCESS

        return STATUS_PARTIAL

    @classmethod
    def from_sections(
        cls,
        page_name: str,
        href: str,
        sections: Dict[str, bool],
        error: Optional[str] = None,
        screenshot_path: Optional[str] = None,
        critical: frozenset = CRITICAL_SECTIONS,
    ) -> "PageResult":
        status = cls.compute_status(sections, critical=critical)
        return cls(
            page_name=page_name,
            href=href,
            status=status,
            sections=dict(sections),
            error=error,
            screenshot_path=screenshot_path,
        )

    @classmethod
    def skipped_result(cls, page_name: str, href: str) -> "PageResult":
        return cls(
            page_name=page_name, href=href, status=STATUS_SKIPPED, sections={}
        )

    @classmethod
    def failed_result(
        cls,
        page_name: str,
        href: str,
        error: str,
        sections: Optional[Dict[str, bool]] = None,
        screenshot_path: Optional[str] = None,
    ) -> "PageResult":
        return cls(
            page_name=page_name,
            href=href,
            status=STATUS_FAILED,
            sections=dict(sections or {}),
            error=error,
            screenshot_path=screenshot_path,
        )

    # -- convenience predicates --

    @property
    def is_success(self) -> bool:
        return self.status == STATUS_SUCCESS

    @property
    def is_partial(self) -> bool:
        return self.status == STATUS_PARTIAL

    @property
    def is_failed(self) -> bool:
        return self.status == STATUS_FAILED

    @property
    def is_skipped(self) -> bool:
        return self.status == STATUS_SKIPPED

    @property
    def created(self) -> bool:
        """Whether a page was actually created (success or partial)."""
        return self.status in (STATUS_SUCCESS, STATUS_PARTIAL)


# --- BatchResult -----------------------------------------------------------


@dataclass
class BatchResult:
    """Aggregate outcome across all pages in a run."""

    pages: List[PageResult] = field(default_factory=list)

    def add(self, result: PageResult) -> None:
        self.pages.append(result)

    @property
    def total(self) -> int:
        return len(self.pages)

    @property
    def success(self) -> int:
        return sum(1 for p in self.pages if p.is_success)

    @property
    def partial(self) -> int:
        return sum(1 for p in self.pages if p.is_partial)

    @property
    def failed(self) -> int:
        return sum(1 for p in self.pages if p.is_failed)

    @property
    def skipped(self) -> int:
        return sum(1 for p in self.pages if p.is_skipped)

    @property
    def created(self) -> int:
        """Pages actually created (success + partial)."""
        return self.success + self.partial

    def summary(self) -> Dict[str, int]:
        return {
            "total": self.total,
            "success": self.success,
            "partial": self.partial,
            "failed": self.failed,
            "skipped": self.skipped,
        }
