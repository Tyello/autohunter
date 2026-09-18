import pytest

from app.services import browser_fetcher
from app.sources.types import ScrapeContext


class _FakeBackendNoWedge:
    def __init__(self, exc):
        self._exc = exc
        self.reset_calls = 0
        self.fetch_calls = 0

    def fetch(self, *_a, **_kw):
        self.fetch_calls += 1
        raise self._exc

    def check_wedged(self, *, threshold_seconds):
        return {"wedged": False}

    def reset(self):
        self.reset_calls += 1


class _FakeBackendWedged(_FakeBackendNoWedge):
    def check_wedged(self, *, threshold_seconds):
        return {"wedged": True}


class _FakeBackendNoWedgeSupport:
    """Mimics the external browser_service client: no check_wedged method."""

    def __init__(self, exc):
        self._exc = exc
        self.reset_calls = 0

    def fetch(self, *_a, **_kw):
        raise self._exc

    def reset(self):
        self.reset_calls += 1


def _ctx():
    return ScrapeContext(source="kavak")


def test_should_reset_after_failure_target_closed_always_resets():
    backend = _FakeBackendNoWedge(Exception("target closed"))
    assert browser_fetcher._should_reset_after_failure(backend, Exception("Target page, context or browser has been closed")) is True


def test_should_reset_after_failure_timeout_not_wedged_does_not_reset():
    backend = _FakeBackendNoWedge(TimeoutError("x"))
    assert browser_fetcher._should_reset_after_failure(backend, TimeoutError("Playwright worker timed out waiting for job 'fetch'.")) is False


def test_should_reset_after_failure_timeout_wedged_resets():
    backend = _FakeBackendWedged(TimeoutError("x"))
    assert browser_fetcher._should_reset_after_failure(backend, TimeoutError("Playwright worker timed out waiting for job 'fetch'.")) is True


def test_should_reset_after_failure_timeout_backend_without_check_wedged_fails_safe():
    backend = _FakeBackendNoWedgeSupport(TimeoutError("x"))
    assert browser_fetcher._should_reset_after_failure(backend, TimeoutError("timed out")) is True


def test_should_reset_after_failure_non_timeout_non_target_closed_does_not_reset():
    backend = _FakeBackendNoWedge(ValueError("boom"))
    assert browser_fetcher._should_reset_after_failure(backend, ValueError("boom")) is False


def test_fetch_html_browser_does_not_reset_pool_on_queue_timeout_when_not_wedged(monkeypatch):
    backend = _FakeBackendNoWedge(TimeoutError("Playwright worker timed out waiting for job 'fetch'."))
    monkeypatch.setattr(browser_fetcher, "_get_backend", lambda: backend)
    monkeypatch.setattr(browser_fetcher.time, "sleep", lambda *_a, **_kw: None)

    with pytest.raises(TimeoutError):
        browser_fetcher.fetch_html_browser("https://x.example/", ctx=_ctx())

    assert backend.fetch_calls == 2  # one retry, per existing retry-on-timeout behavior
    assert backend.reset_calls == 0  # not wedged: reactive reset must not fire


def test_fetch_html_browser_resets_pool_when_worker_genuinely_wedged(monkeypatch):
    backend = _FakeBackendWedged(TimeoutError("Playwright worker timed out waiting for job 'fetch'."))
    monkeypatch.setattr(browser_fetcher, "_get_backend", lambda: backend)
    monkeypatch.setattr(browser_fetcher.time, "sleep", lambda *_a, **_kw: None)

    with pytest.raises(TimeoutError):
        browser_fetcher.fetch_html_browser("https://x.example/", ctx=_ctx())

    assert backend.reset_calls >= 1


def test_fetch_html_browser_releases_dispatch_semaphore_on_failure(monkeypatch):
    """Regression guard: a leaked semaphore permit would permanently shrink
    dispatch capacity after every failed fetch.
    """
    backend = _FakeBackendNoWedge(TimeoutError("Playwright worker timed out waiting for job 'fetch'."))
    monkeypatch.setattr(browser_fetcher, "_get_backend", lambda: backend)
    monkeypatch.setattr(browser_fetcher.time, "sleep", lambda *_a, **_kw: None)
    monkeypatch.setattr(browser_fetcher.settings, "playwright_max_inflight_dispatches", 1)

    for _ in range(3):
        with pytest.raises(TimeoutError):
            browser_fetcher.fetch_html_browser("https://x.example/", ctx=_ctx())

    sem = browser_fetcher._get_dispatch_semaphore()
    assert sem.acquire(timeout=0) is True
    sem.release()
