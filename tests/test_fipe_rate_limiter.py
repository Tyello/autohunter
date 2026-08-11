from __future__ import annotations

import threading
import time

import pytest

from app.services.fipe_rate_limiter import FipeRateLimiter


def test_acquire_paces_single_thread(monkeypatch):
    clock = {"t": 1_000_000.0}
    sleeps = []

    def fake_monotonic():
        return clock["t"]

    def fake_sleep(seconds):
        sleeps.append(seconds)
        clock["t"] += seconds

    monkeypatch.setattr(time, "monotonic", fake_monotonic)
    monkeypatch.setattr(time, "sleep", fake_sleep)

    limiter = FipeRateLimiter(rate_limit_ms=800, max_throttle_ms=5000, recovery_after_successes=20)

    limiter.acquire()
    assert sleeps == []

    limiter.acquire()
    assert len(sleeps) == 1
    assert sleeps[0] == pytest.approx(0.8)


def test_concurrent_acquire_respects_aggregate_rate():
    rate_limit_ms = 10
    limiter = FipeRateLimiter(rate_limit_ms=rate_limit_ms, max_throttle_ms=5000, recovery_after_successes=1000)

    n_threads = 5
    calls_per_thread = 4
    total_calls = n_threads * calls_per_thread

    def worker():
        for _ in range(calls_per_thread):
            limiter.acquire()

    start = time.monotonic()
    threads = [threading.Thread(target=worker) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.monotonic() - start

    min_expected_elapsed_s = (total_calls - 1) * (rate_limit_ms / 1000)
    assert elapsed >= min_expected_elapsed_s * 0.9


def test_on_429_doubles_then_recovers_after_successes():
    limiter = FipeRateLimiter(rate_limit_ms=800, max_throttle_ms=5000, recovery_after_successes=5)

    limiter.on_429()
    assert limiter.current_throttle_ms == 1600

    for _ in range(5):
        limiter.on_success()

    assert limiter.current_throttle_ms < 1600
    assert limiter.current_throttle_ms >= 800


def test_recovery_never_goes_below_base_rate():
    limiter = FipeRateLimiter(rate_limit_ms=800, max_throttle_ms=5000, recovery_after_successes=3)

    for _ in range(30):
        limiter.on_success()

    assert limiter.current_throttle_ms == 800
