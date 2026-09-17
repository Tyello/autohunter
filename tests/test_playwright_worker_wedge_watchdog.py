from __future__ import annotations

import time

import app.services.playwright_pool as pw_pool
from app.services.playwright_pool import PlaywrightPool, recover_if_wedged


class _FakeWorker:
    def __init__(self, *, alive=True, job_started_at=None, job_name=None):
        self._alive = alive
        self.job_started_at = job_started_at
        self.current_job_name = job_name

    def is_alive(self):
        return self._alive


def test_check_wedged_reports_not_wedged_when_idle():
    pool = PlaywrightPool()
    pool._worker = _FakeWorker(job_started_at=None)

    result = pool.check_wedged(threshold_seconds=150)

    assert result["wedged"] is False
    assert result["alive"] is True


def test_check_wedged_reports_not_wedged_when_job_still_within_threshold():
    pool = PlaywrightPool()
    pool._worker = _FakeWorker(job_started_at=time.time() - 5, job_name="fetch")

    result = pool.check_wedged(threshold_seconds=150)

    assert result["wedged"] is False


def test_check_wedged_reports_wedged_past_threshold():
    pool = PlaywrightPool()
    pool._worker = _FakeWorker(job_started_at=time.time() - 200, job_name="fetch")

    result = pool.check_wedged(threshold_seconds=150)

    assert result["wedged"] is True
    assert result["job_name"] == "fetch"
    assert result["elapsed_seconds"] > 150


def test_check_wedged_false_when_no_worker():
    pool = PlaywrightPool()
    pool._worker = None

    result = pool.check_wedged(threshold_seconds=150)

    assert result["wedged"] is False
    assert result["alive"] is False


def test_recover_if_wedged_noop_when_no_pool(monkeypatch):
    monkeypatch.setattr(pw_pool, "_POOL", None)

    result = recover_if_wedged(threshold_seconds=150)

    assert result == {"ok": True, "wedged": False, "action": "none"}


def test_recover_if_wedged_does_nothing_when_healthy(monkeypatch):
    pool = PlaywrightPool()
    pool._worker = _FakeWorker(job_started_at=time.time() - 5, job_name="fetch")
    reset_calls = []
    pool.reset = lambda: reset_calls.append(1) or {"stopped_cleanly": True, "force_killed": 0}
    monkeypatch.setattr(pw_pool, "_POOL", pool)

    result = recover_if_wedged(threshold_seconds=150)

    assert result["action"] == "none"
    assert reset_calls == []


def test_recover_if_wedged_resets_pool_when_wedged(monkeypatch):
    pool = PlaywrightPool()
    pool._worker = _FakeWorker(job_started_at=time.time() - 300, job_name="fetch")
    reset_calls = []
    pool.reset = lambda: (reset_calls.append(1), {"stopped_cleanly": False, "force_killed": 1})[1]
    monkeypatch.setattr(pw_pool, "_POOL", pool)

    result = recover_if_wedged(threshold_seconds=150)

    assert result["ok"] is True
    assert result["action"] == "reset"
    assert reset_calls == [1]
    assert result["close_result"] == {"stopped_cleanly": False, "force_killed": 1}


def test_recover_if_wedged_reports_failure_if_reset_raises(monkeypatch):
    pool = PlaywrightPool()
    pool._worker = _FakeWorker(job_started_at=time.time() - 300, job_name="fetch")

    def _boom():
        raise RuntimeError("kill failed")

    pool.reset = _boom
    monkeypatch.setattr(pw_pool, "_POOL", pool)

    result = recover_if_wedged(threshold_seconds=150)

    assert result["ok"] is False
    assert result["action"] == "reset_failed"
    assert "kill failed" in result["error"]
