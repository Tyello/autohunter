"""Tests for app.scheduler.worker_threads — daemon thread helpers."""

from __future__ import annotations

import pytest
import threading
import time

from app.core import shutdown as shutdown_state
from app.scheduler.worker_threads import (
    start_worker_thread,
    stop_worker_threads,
    WORKER_THREADS,
)


@pytest.fixture(autouse=True)
def reset_shutdown_state():
    """Reset shutdown state before and after each test."""
    shutdown_state._shutdown_event.clear()
    shutdown_state._shutdown_reason = None
    yield
    shutdown_state._shutdown_event.clear()
    shutdown_state._shutdown_reason = None


@pytest.fixture(autouse=True)
def clear_worker_threads():
    """Clear the worker thread registry before and after each test."""
    WORKER_THREADS.clear()
    yield
    WORKER_THREADS.clear()


def test_worker_thread_calls_fn_multiple_times():
    """With small interval, fn should be called at least 2 times in ~0.2s."""
    counter = {"value": 0}

    def increment():
        counter["value"] += 1

    thread = start_worker_thread(increment, seconds=0.05, name="test_counter")
    assert thread.is_alive()
    assert thread in WORKER_THREADS

    time.sleep(0.2)

    # Request shutdown and wait for it
    shutdown_state.request_shutdown("test")
    stop_worker_threads(timeout=2)

    # Thread should have called fn at least twice in 0.2s with 0.05s interval
    assert counter["value"] >= 2


def test_worker_thread_stops_after_shutdown():
    """After shutdown request, fn should not be called anymore."""
    counter = {"value": 0}

    def increment():
        counter["value"] += 1
        time.sleep(0.01)  # Small delay to ensure measurable calls

    thread = start_worker_thread(increment, seconds=0.05, name="test_shutdown_stop")
    assert thread.is_alive()

    time.sleep(0.15)
    count_before = counter["value"]

    # Request shutdown
    shutdown_state.request_shutdown("test")

    # Small delay to let thread finish current iteration and exit loop
    time.sleep(0.1)

    count_after = counter["value"]

    # Counter should not have grown after shutdown
    # (may grow by 1 if thread was in the middle of fn(), but not more)
    assert count_after <= count_before + 1
    assert count_before >= 1


def test_stop_worker_threads_returns_without_hanging():
    """stop_worker_threads should return promptly without blocking."""
    counter = {"value": 0}

    def noop():
        counter["value"] += 1

    thread = start_worker_thread(noop, seconds=0.05, name="test_no_hang")
    time.sleep(0.2)

    # Request shutdown
    shutdown_state.request_shutdown("test")

    # Should not hang; measure that it returns quickly
    start = time.time()
    stop_worker_threads(timeout=2)
    elapsed = time.time() - start

    # Should return in less than 1 second (much faster than the 2s timeout)
    assert elapsed < 1.0
    assert not thread.is_alive()
    assert len(WORKER_THREADS) == 0


def test_worker_thread_exception_does_not_kill_loop():
    """Exception in fn should be logged and loop should continue."""
    counter = {"value": 0, "errors": 0}

    def failing_fn():
        counter["value"] += 1
        if counter["value"] % 2 == 0:
            counter["errors"] += 1
            raise ValueError("Test exception")

    thread = start_worker_thread(failing_fn, seconds=0.05, name="test_exceptions")

    time.sleep(0.2)
    shutdown_state.request_shutdown("test")
    stop_worker_threads(timeout=2)

    # Should have called fn multiple times despite some failures
    assert counter["value"] >= 2
    assert counter["errors"] >= 1
    assert not thread.is_alive()
