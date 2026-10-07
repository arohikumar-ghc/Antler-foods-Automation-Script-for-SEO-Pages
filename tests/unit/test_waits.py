"""Unit tests for retry/wait helpers (Step 9).

These tests use an injected sleeper so they are instant and deterministic; they
do not launch a browser.
"""
import pytest

from antler_seo.automation.waits import RetryError, retry


class _Counter:
    def __init__(self):
        self.calls = 0


def _recording_sleeper():
    delays = []

    def sleeper(d):
        delays.append(d)

    return delays, sleeper


def test_succeeds_immediately():
    counter = _Counter()

    def op():
        counter.calls += 1
        return "ok"

    delays, sleeper = _recording_sleeper()
    result = retry(op, attempts=3, sleeper=sleeper)

    assert result == "ok"
    assert counter.calls == 1
    assert delays == []  # no retries, no sleeps


def test_succeeds_after_transient_failures():
    counter = _Counter()

    def op():
        counter.calls += 1
        if counter.calls < 3:
            raise ValueError("transient")
        return "recovered"

    delays, sleeper = _recording_sleeper()
    result = retry(op, attempts=5, base_delay=0.5, backoff_factor=2.0, sleeper=sleeper)

    assert result == "recovered"
    assert counter.calls == 3
    # Two retries occurred -> two sleeps with exponential backoff.
    assert delays == [0.5, 1.0]


def test_fails_after_budget_exhausted():
    counter = _Counter()

    def op():
        counter.calls += 1
        raise ValueError("always fails")

    delays, sleeper = _recording_sleeper()
    with pytest.raises(RetryError) as exc:
        retry(op, attempts=3, base_delay=0.1, sleeper=sleeper)

    assert counter.calls == 3  # bounded: exactly `attempts` calls
    assert exc.value.attempts == 3
    assert isinstance(exc.value.last_exception, ValueError)
    assert len(delays) == 2  # sleeps only between attempts, not after the last


def test_retry_count_is_bounded():
    counter = _Counter()

    def op():
        counter.calls += 1
        raise RuntimeError("boom")

    _, sleeper = _recording_sleeper()
    with pytest.raises(RetryError):
        retry(op, attempts=1, sleeper=sleeper)

    assert counter.calls == 1  # attempts=1 means a single try, no retry


def test_backoff_is_capped_by_max_delay():
    def op():
        raise ValueError("fail")

    delays, sleeper = _recording_sleeper()
    with pytest.raises(RetryError):
        retry(
            op,
            attempts=5,
            base_delay=1.0,
            backoff_factor=10.0,
            max_delay=5.0,
            sleeper=sleeper,
        )

    # Raw would be 1, 10, 100, 1000; capped at 5.
    assert delays == [1.0, 5.0, 5.0, 5.0]


def test_non_retryable_exception_propagates_immediately():
    counter = _Counter()

    def op():
        counter.calls += 1
        raise KeyError("not retryable here")

    _, sleeper = _recording_sleeper()
    with pytest.raises(KeyError):
        retry(op, attempts=5, retry_on=(ValueError,), sleeper=sleeper)

    assert counter.calls == 1  # KeyError not in retry_on -> no retries


def test_invalid_attempts_rejected():
    with pytest.raises(ValueError):
        retry(lambda: None, attempts=0)
