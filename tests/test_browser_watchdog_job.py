from __future__ import annotations

import pytest

from app.core import shutdown as shutdown_state
from app.scheduler import browser_watchdog_job


@pytest.fixture(autouse=True)
def reset_shutdown_state():
    shutdown_state._shutdown_event.clear()
    shutdown_state._shutdown_reason = None
    yield
    shutdown_state._shutdown_event.clear()
    shutdown_state._shutdown_reason = None


class _DummyDb:
    def commit(self):
        pass


class _DummySessionCtx:
    def __enter__(self):
        return _DummyDb()

    def __exit__(self, *exc):
        return False


def test_heartbeat_watchdog_noop_when_playwright_disabled(monkeypatch):
    monkeypatch.setattr(browser_watchdog_job.settings, "enable_playwright", False)
    called = {"n": 0}
    monkeypatch.setattr(
        browser_watchdog_job, "SessionLocal", lambda: called.__setitem__("n", called["n"] + 1)
    )

    browser_watchdog_job.job_browser_worker_heartbeat_watchdog()

    assert called["n"] == 0


def test_heartbeat_watchdog_noop_during_shutdown(monkeypatch):
    monkeypatch.setattr(browser_watchdog_job.settings, "enable_playwright", True)
    shutdown_state.request_shutdown("test")
    called = {"n": 0}
    monkeypatch.setattr(
        browser_watchdog_job, "SessionLocal", lambda: called.__setitem__("n", called["n"] + 1)
    )

    browser_watchdog_job.job_browser_worker_heartbeat_watchdog()

    assert called["n"] == 0


def test_heartbeat_watchdog_logs_warn_on_reset(monkeypatch):
    monkeypatch.setattr(browser_watchdog_job.settings, "enable_playwright", True)
    monkeypatch.setattr(browser_watchdog_job, "SessionLocal", lambda: _DummySessionCtx())

    import app.services.playwright_pool as pw_pool

    monkeypatch.setattr(
        pw_pool,
        "recover_if_wedged",
        lambda **_k: {"ok": True, "action": "reset", "wedged": True, "job_name": "fetch", "elapsed_seconds": 300},
    )

    logged = []
    monkeypatch.setattr(browser_watchdog_job, "log", lambda db, level, component, message, payload: logged.append((level, message)))

    browser_watchdog_job.job_browser_worker_heartbeat_watchdog()

    assert logged == [("warn", "worker_wedge_reset")]


def test_heartbeat_watchdog_logs_debug_when_healthy(monkeypatch):
    monkeypatch.setattr(browser_watchdog_job.settings, "enable_playwright", True)
    monkeypatch.setattr(browser_watchdog_job, "SessionLocal", lambda: _DummySessionCtx())

    import app.services.playwright_pool as pw_pool

    monkeypatch.setattr(
        pw_pool,
        "recover_if_wedged",
        lambda **_k: {"ok": True, "action": "none", "wedged": False},
    )

    logged = []
    monkeypatch.setattr(browser_watchdog_job, "log", lambda db, level, component, message, payload: logged.append((level, message)))

    browser_watchdog_job.job_browser_worker_heartbeat_watchdog()

    assert logged == [("debug", "worker_heartbeat_ok")]
