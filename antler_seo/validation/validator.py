"""
Pre-flight validation for a batch of SEO pages.

Runs entirely before any browser work (this module never launches a browser).
It catches authoring errors early so a run doesn't fail halfway through the UI.

Checks performed:
  * required fields (delegated to :meth:`SEOPage.validate`)
  * href format rules (leading slash, lowercase, no spaces, allowed chars)
  * FAQ rules (delegated to the model)
  * duplicate href detection across the batch
  * optional declared page-count mismatch (warning)
  * image reference validation ONLY when images are explicitly enabled

Errors fail validation; warnings do not. Image handling is OFF by default: with
images disabled no image checks run at all (no dead validation).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from antler_seo.models import SEOPage

# A conservative, SEO-friendly slug: leading slash, then lowercase letters,
# digits, hyphens and single-level path separators.
_HREF_RE = re.compile(r"^/[a-z0-9]+(?:[-/][a-z0-9]+)*$")


@dataclass
class PageValidation:
    """Validation outcome for a single page."""

    index: int  # 1-based position in the batch
    page_name: str
    href: str
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.errors


@dataclass
class ValidationReport:
    """Aggregate validation outcome for a batch."""

    pages: List[PageValidation] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)  # batch-level errors
    warnings: List[str] = field(default_factory=list)  # batch-level warnings

    @property
    def passed(self) -> bool:
        batch_ok = not self.errors
        pages_ok = all(p.passed for p in self.pages)
        return batch_ok and pages_ok

    @property
    def valid_pages(self) -> List[int]:
        """1-based indexes of pages that passed."""
        return [p.index for p in self.pages if p.passed]

    def total_errors(self) -> int:
        return len(self.errors) + sum(len(p.errors) for p in self.pages)

    def total_warnings(self) -> int:
        return len(self.warnings) + sum(len(p.warnings) for p in self.pages)


def _validate_href_format(href: str) -> List[str]:
    """Return href format problems (presence/leading-slash handled elsewhere)."""
    problems: List[str] = []
    if not href:
        return problems  # presence handled by model validation
    if " " in href:
        problems.append("href must not contain spaces")
    if href != href.lower():
        problems.append("href must be lowercase")
    # Only run the structural regex if the simple checks pass, for clearer msgs.
    if not problems and not _HREF_RE.match(href):
        problems.append(
            "href must be a slug of lowercase letters, digits and hyphens "
            "(e.g. /butter-chicken)"
        )
    return problems


def validate_pages(
    pages: List[SEOPage],
    *,
    expected_page_count: Optional[int] = None,
    images_enabled: bool = False,
    image_dir: Optional[str] = None,
) -> ValidationReport:
    """Validate a batch of SEO pages before automation.

    Args:
        pages: Parsed pages to validate.
        expected_page_count: If provided, a mismatch adds a batch-level warning.
        images_enabled: When False (default), no image checks run.
        image_dir: Directory to resolve image filenames against when images are
            enabled. If omitted, a page with an image is flagged as unresolvable.

    Returns:
        A :class:`ValidationReport`. This function never launches a browser.
    """
    report = ValidationReport()

    if not pages:
        report.errors.append("No pages to validate")
        return report

    seen_hrefs: dict[str, int] = {}

    for i, page in enumerate(pages, 1):
        pv = PageValidation(index=i, page_name=page.page_name, href=page.href)

        # Required fields + FAQ rules (model-level).
        pv.errors.extend(page.validate())

        # href format rules.
        pv.errors.extend(_validate_href_format(page.href))

        # Duplicate href detection.
        if page.href:
            if page.href in seen_hrefs:
                pv.errors.append(
                    f"duplicate href '{page.href}' (also used by page "
                    f"{seen_hrefs[page.href]})"
                )
            else:
                seen_hrefs[page.href] = i

        # Image validation only when explicitly enabled.
        if images_enabled and page.image is not None:
            pv.errors.extend(_validate_image(page, image_dir))

        report.pages.append(pv)

    # Optional declared page-count mismatch (warning, not an error).
    if expected_page_count is not None and expected_page_count != len(pages):
        report.warnings.append(
            f"page count mismatch: expected {expected_page_count}, "
            f"found {len(pages)}"
        )

    return report


def _validate_image(page: SEOPage, image_dir: Optional[str]) -> List[str]:
    """Validate a page's image reference (only called when images enabled)."""
    problems: List[str] = []
    filename = page.image.filename if page.image else ""
    if not filename.strip():
        problems.append("image reference is empty")
        return problems

    if not image_dir:
        problems.append(
            f"image '{filename}' cannot be resolved: no image directory provided"
        )
        return problems

    candidate = Path(image_dir) / filename
    if not candidate.exists():
        problems.append(f"image file not found: {candidate}")

    return problems
