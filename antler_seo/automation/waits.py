"""
Event-driven wait helpers and a bounded retry wrapper.

Philosophy:
* Prefer Playwright's own event-driven waits (``locator.wait_for``,
  ``expect``, ``wait_for_load_state``) over arbitrary ``sleep()`` calls.
* :func:`retry` provides a *bounded* retry policy with predictable backoff for
  genuinely transient failures. It never loops unbounded.

The retry backoff uses an injectable ``sleeper`` so tests are deterministic and
instant; production uses ``time.sleep``. There are no fixed sleeps baked into
the wait helpers themselves.
"""
from __future__ import annotations

import time
from typing import Callable, Iterable, Optional, Tuple, Type, TypeVar

from playwright.sync_api import Locator, Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from antler_seo.logging_setup import get_logger

logger = get_logger("automation.waits")

T = TypeVar("T")


class RetryError(Exception):
    """Raised when a retried operation exhausts its attempt budget."""

    def __init__(self, attempts: int, last_exception: BaseException):
        self.attempts = attempts
        self.last_exception = last_exception
        super().__init__(
            f"Operation failed after {attempts} attempt(s): {last_exception!r}"
        )


def retry(
    operation: Callable[[], T],
    *,
    attempts: int = 3,
    base_delay: float = 0.5,
    backoff_factor: float = 2.0,
    max_delay: Optional[float] = None,
    retry_on: Tuple[Type[BaseException], ...] = (Exception,),
    sleeper: Callable[[float], None] = time.sleep,
    description: str = "operation",
) -> T:
    """Run ``operation`` with bounded retries and predictable backoff.

    Args:
        operation: Zero-argument callable to execute.
        attempts: Maximum number of attempts (must be >= 1).
        base_delay: Delay before the first retry, in seconds.
        backoff_factor: Multiplier applied to the delay after each failure
            (1.0 = constant delay, 2.0 = exponential doubling).
        max_delay: Optional cap on the per-retry delay.
        retry_on: Exception types that trigger a retry. Others propagate
            immediately.
        sleeper: Callable used to wait between attempts (injectable for tests).
        description: Human-readable label for logging.

    Returns:
        The operation's return value on the first successful attempt.

    Raises:
        RetryError: If all attempts fail with a retryable exception.
        ValueError: If ``attempts`` < 1.
    """
    if attempts < 1:
        raise ValueError("attempts must be >= 1")

    delay = base_delay
    last_exc: Optional[BaseException] = None

    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except retry_on as exc:
            last_exc = exc
            if attempt < attempts:
                logger.debug(
                    "%s failed (attempt %d/%d): %r; retrying in %.2fs",
                    description,
                    attempt,
                    attempts,
                    exc,
                    delay,
                )
                if delay > 0:
                    sleeper(delay)
                delay = delay * backoff_factor
                if max_delay is not None:
                    delay = min(delay, max_delay)
            else:
                logger.debug(
                    "%s failed (attempt %d/%d): %r; budget exhausted",
                    description,
                    attempt,
                    attempts,
                    exc,
                )

    assert last_exc is not None  # loop ran at least once
    raise RetryError(attempts=attempts, last_exception=last_exc)


def wait_for_visible(
    target: Locator,
    timeout_ms: Optional[int] = None,
) -> Locator:
    """Wait until a locator is visible (event-driven) and return it.

    Raises:
        PlaywrightTimeoutError: If the element does not become visible in time.
    """
    target.wait_for(state="visible", timeout=timeout_ms)
    return target


def wait_for_attached(
    target: Locator,
    timeout_ms: Optional[int] = None,
) -> Locator:
    """Wait until a locator is attached to the DOM and return it."""
    target.wait_for(state="attached", timeout=timeout_ms)
    return target


def wait_for_hidden(
    target: Locator,
    timeout_ms: Optional[int] = None,
) -> Locator:
    """Wait until a locator is hidden/detached and return it."""
    target.wait_for(state="hidden", timeout=timeout_ms)
    return target


def is_visible(target: Locator, timeout_ms: int = 1000) -> bool:
    """Return True if the locator becomes visible within a short timeout.

    Swallows Playwright timeouts so callers can branch on presence without a
    try/except at every call site.
    """
    try:
        target.wait_for(state="visible", timeout=timeout_ms)
        return True
    except PlaywrightTimeoutError:
        return False


def wait_for_load(
    page: Page,
    state: str = "domcontentloaded",
    timeout_ms: Optional[int] = None,
) -> None:
    """Wait for a page load state (``domcontentloaded`` by default).

    ``domcontentloaded`` is preferred over ``networkidle`` for modern SPA-style
    apps, which may never reach network idle.
    """
    page.wait_for_load_state(state, timeout=timeout_ms)
