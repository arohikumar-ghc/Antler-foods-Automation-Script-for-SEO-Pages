"""
Reporting: per-restaurant result aggregation + status/notes for Sheet write-back.

Builds on the existing status model in :mod:`antler_seo.models`
(:class:`PageResult` / :class:`BatchResult`). ``RestaurantResult`` adds the
restaurant/tenant context and the source document, and derives the exact values
the GoogleSheetWriter writes to columns E:G (Completed / Last Run / Notes).

"Completed = Yes" means the full restaurant automation succeeded: the Doc was
read, pages parsed/validated, the restaurant selected, and every required page
processed with its required sections saved — no blocking page failures.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from antler_seo.models import BatchResult, PageResult

COMPLETED_YES = "Yes"
COMPLETED_NO = "No"

_MAX_NOTES_LEN = 480


def format_duration(seconds: Optional[float]) -> str:
    """Format an elapsed duration as '5 min 10 sec' / '42 sec'.

    Returns '' when ``seconds`` is None (unknown).
    """
    if seconds is None:
        return ""
    secs = int(round(seconds))
    if secs < 0:
        secs = 0
    minutes, secs = divmod(secs, 60)
    if minutes:
        return f"{minutes} min {secs} sec"
    return f"{secs} sec"


@dataclass
class RestaurantResult:
    """Outcome of processing one restaurant (one Sheet row)."""

    restaurant_name: str
    row_number: int
    source_doc: str = ""
    batch: BatchResult = field(default_factory=BatchResult)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    # True only when the restaurant reached page processing (Doc read, parsed,
    # validated, restaurant selected). A pre-processing failure sets this False.
    reached_processing: bool = False
    # Per-restaurant elapsed processing time in seconds (set by the
    # orchestrator); None until measured.
    elapsed_seconds: Optional[float] = None

    def add_page(self, result: PageResult) -> None:
        self.batch.add(result)

    def add_error(self, message: str) -> None:
        self.errors.append(message)

    def add_warning(self, message: str) -> None:
        self.warnings.append(message)

    # -- derived counts --

    @property
    def total(self) -> int:
        return self.batch.total

    @property
    def success(self) -> int:
        return self.batch.success

    @property
    def partial(self) -> int:
        return self.batch.partial

    @property
    def failed(self) -> int:
        return self.batch.failed

    @property
    def skipped(self) -> int:
        return self.batch.skipped

    @property
    def has_blocking_failures(self) -> bool:
        """A restaurant is NOT complete if any required page failed/partial."""
        return self.failed > 0 or self.partial > 0

    @property
    def is_complete(self) -> bool:
        """True only when the full automation succeeded with no blocking issues.

        Requires: reached page processing, no pre-processing errors, at least
        one page created, and no failed/partial pages. (All-skipped counts as
        complete: nothing needed doing.)
        """
        if not self.reached_processing or self.errors:
            return False
        if self.total == 0:
            return False
        if self.has_blocking_failures:
            return False
        return True

    # -- Sheet write-back values (columns E:G) --

    def completed_value(self) -> str:
        """Legacy Yes/No flag (kept for console/gating; not written to E)."""
        return COMPLETED_YES if self.is_complete else COMPLETED_NO

    def completed_cell(self) -> str:
        """Column E: count of successfully created pages.

        Complete runs → ``"N pages created"`` (recognised as done by
        pending-row detection). Incomplete runs are prefixed with
        ``"INCOMPLETE: "`` so the row remains pending and is retried, while still
        recording the real created count. Skipped/failed pages are NOT counted
        as created.
        """
        unit = "page" if self.success == 1 else "pages"
        base = f"{self.success} {unit} created"
        return base if self.is_complete else f"INCOMPLETE: {base}"

    def elapsed_cell(self) -> str:
        """Column F: per-restaurant elapsed processing time."""
        return format_duration(self.elapsed_seconds)

    def notes(self) -> str:
        """Column G: concise created/skipped/partial/failed summary + errors.

        Clearly flags incomplete runs; never reports a partial run as complete.
        """
        if self.errors and not self.reached_processing:
            text = "Failed before processing: " + "; ".join(self.errors)
        else:
            status = "Complete" if self.is_complete else "INCOMPLETE"
            text = (
                f"{status}: created {self.success}, skipped {self.skipped}, "
                f"partial {self.partial}, failed {self.failed}, of {self.total}"
            )
            if self.errors:
                text += " | errors: " + "; ".join(self.errors)
            if self.warnings:
                text += " | warnings: " + "; ".join(self.warnings[:3])
        return text[:_MAX_NOTES_LEN]

    def console_summary(self) -> str:
        """Human-readable multi-line summary for logs/console."""
        lines = [
            f"Restaurant: {self.restaurant_name} (row {self.row_number})",
            f"  Source doc: {_mask(self.source_doc)}",
            f"  Completed:  {self.completed_value()}",
            f"  Column E:   {self.completed_cell()}",
            f"  Elapsed:    {self.elapsed_cell() or '(not measured)'}",
            f"  Pages: total={self.total} success={self.success} "
            f"partial={self.partial} failed={self.failed} skipped={self.skipped}",
        ]
        for p in self.batch.pages:
            lines.append(f"    [{p.status}] {p.page_name} ({p.href})"
                         + (f" — {p.error}" if p.error else ""))
        for e in self.errors:
            lines.append(f"  error: {e}")
        for w in self.warnings:
            lines.append(f"  warning: {w}")
        return "\n".join(lines)


def _mask(url: str) -> str:
    """Mask a doc URL/id for logs (don't expose the full link)."""
    if not url:
        return "(none)"
    return f"present (len={len(url)})"
