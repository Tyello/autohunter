from __future__ import annotations

import pytest

from app.core import shutdown as shutdown_state


@pytest.fixture(autouse=True)
def reset_shutdown_state():
    shutdown_state._shutdown_event.clear()
    shutdown_state._shutdown_reason = None
    yield
    shutdown_state._shutdown_event.clear()
    shutdown_state._shutdown_reason = None


def test_run_scheduler_graceful_shutdown(monkeypatch):
    from app.cli import run_scheduler

    class DummySched:
        def __init__(self):
            self.paused = False
            self.shutdown_wait = None

        def pause(self):
            self.paused = True

        def shutdown(self, wait=False):
            self.shutdown_wait = wait

    sched = DummySched()
    monkeypatch.setattr(run_scheduler, "start_scheduler", lambda: sched)
    monkeypatch.setattr(run_scheduler.time, "sleep", lambda _s: shutdown_state.request_shutdown("test"))

    rc = run_scheduler.main()
    assert rc == 0
    assert sched.paused is True
    assert sched.shutdown_wait is True


def test_tick_does_not_enqueue_during_shutdown(monkeypatch):
    from app.scheduler import run as scheduler_run

    shutdown_state.request_shutdown("test")
    called = {"enqueue": 0}

    monkeypatch.setattr(scheduler_run, "get_source", lambda _s: object())
    monkeypatch.setattr(scheduler_run, "enqueue_job", lambda *_a, **_k: called.__setitem__("enqueue", called["enqueue"] + 1))

    scheduler_run.job_run_source_for_all_wishlists("olx")
    assert called["enqueue"] == 0


def test_heartbeat_rolls_back_and_logs_short_error(monkeypatch, capsys):
    from app.scheduler import run as scheduler_run

    class DummyDB:
        def __init__(self):
            self.rolled_back = False
            self.closed = False

        def commit(self):
            raise RuntimeError("relation system_logs does not exist")

        def rollback(self):
            self.rolled_back = True

        def close(self):
            self.closed = True

    db = DummyDB()
    monkeypatch.setattr(scheduler_run, "SessionLocal", lambda: db)
    monkeypatch.setattr(scheduler_run, "heartbeat", lambda _db: None)
    monkeypatch.setattr(scheduler_run, "_last_heartbeat_error_log_at", None)

    scheduler_run.job_heartbeat()

    out = capsys.readouterr().out
    assert db.rolled_back is True
    assert db.closed is True
    assert "heartbeat_failed" in out
    assert "alembic upgrade head" in out


def test_http_worker_does_not_dequeue_during_shutdown(monkeypatch):
    from app.scheduler import http_queue_job

    shutdown_state.request_shutdown("test")
    called = {"dequeue": 0}
    monkeypatch.setattr(http_queue_job, "dequeue_next_job", lambda *_a, **_k: called.__setitem__("dequeue", called["dequeue"] + 1))

    http_queue_job.job_http_queue_worker()
    assert called["dequeue"] == 0


def test_browser_worker_does_not_dequeue_during_shutdown(monkeypatch):
    from app.scheduler import browser_queue_job

    shutdown_state.request_shutdown("test")
    called = {"dequeue": 0}
    monkeypatch.setattr(browser_queue_job.settings, "enable_playwright", True)
    monkeypatch.setattr(browser_queue_job, "dequeue_next_job", lambda *_a, **_k: called.__setitem__("dequeue", called["dequeue"] + 1))

    browser_queue_job.job_browser_queue_worker()
    assert called["dequeue"] == 0


def test_interpreter_shutdown_error_not_marked_failed_and_logged(monkeypatch):
    from app.scheduler import http_queue_job

    class DummyJob:
        source = "olx"

    class DummyDB:
        def __init__(self):
            self.commits = 0

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def commit(self):
            self.commits += 1

    db = DummyDB()
    marks = {"failed": 0}
    logs: list[tuple[str, str, str, dict]] = []

    monkeypatch.setattr(http_queue_job, "SessionLocal", lambda: db)
    monkeypatch.setattr(http_queue_job, "dequeue_next_job", lambda *_a, **_k: DummyJob())
    monkeypatch.setattr(
        http_queue_job,
        "run_source_for_all_wishlists",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("cannot schedule new futures after interpreter shutdown")),
    )
    monkeypatch.setattr(http_queue_job, "mark_failed", lambda *_a, **_k: marks.__setitem__("failed", marks["failed"] + 1))
    monkeypatch.setattr(http_queue_job, "log", lambda _db, level, component, event_type, payload: logs.append((level, component, event_type, payload)))

    http_queue_job.job_http_queue_worker()

    assert marks["failed"] == 0
    assert any(event_type == "shutdown_suppressed" for _level, _component, event_type, _payload in logs)
    assert db.commits >= 1
