"""Offline tests for pending-row detection with the new 'N pages created' E."""
import pytest

from antler_seo.input.google_sheet import RestaurantRow


def _row(completed):
    return RestaurantRow(
        row_number=2, restaurant_name="R", doc_link="d", image_folder="",
        no_of_pages="", completed=completed, last_run="", notes="",
    )


@pytest.mark.parametrize(
    "completed,pending",
    [
        # Empty / explicit not-done -> pending.
        ("", True),
        ("   ", True),
        ("no", True),
        ("No", True),
        ("pending", True),
        # Legacy done values -> NOT pending (backward compatible).
        ("yes", False),
        ("Yes", False),
        ("  YES  ", False),
        ("y", False),
        ("completed", False),
        ("Completed", False),
        ("COMPLETED", False),
        # New success format -> NOT pending.
        ("10 pages created", False),
        ("1 page created", False),
        ("  7 Pages Created  ", False),
        # Incomplete marker -> stays pending (must be retried).
        ("INCOMPLETE: 7 pages created", True),
        ("INCOMPLETE: 0 pages created", True),
        # Near-misses that must NOT be read as done.
        ("pages created", True),
        ("10 pages", True),
        ("created 10 pages", True),
        ("10 pages created soon", True),
    ],
)
def test_is_pending(completed, pending):
    assert _row(completed).is_pending is pending
