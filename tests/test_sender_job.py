from __future__ import annotations

from app.scheduler.sender_job import job_send_notifications


class _FakeSession:
    def __init__(self):
        self.events: list[str] = []
        self.fail_commit = True

    def commit(self):
        self.events.append("commit")
        if self.fail_commit:
            raise RuntimeError("transaction aborted")

    def rollback(self):
        self.events.append("rollback")


class _FakeSessionContext:
    def __init__(self, session):
        self.session = session

    def __enter__(self):
        return self.session

    def __exit__(self, exc_type, exc, tb):
        return False


def test_sender_job_rolls_back_before_error_log(monkeypatch):
    session = _FakeSession()

    monkeypatch.setattr("app.scheduler.sender_job.is_shutdown_requested", lambda: False)
    monkeypatch.setattr("app.scheduler.sender_job.SessionLocal", lambda: _FakeSessionContext(session))
    monkeypatch.setattr("app.scheduler.sender_job.send_queued_notifications", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")))

    def _fake_log(_db, level, *_args, **_kwargs):
        session.events.append(f"log:{level}")

    monkeypatch.setattr("app.scheduler.sender_job.log", _fake_log)

    job_send_notifications()

    assert session.events[0] == "rollback"
    assert session.events[1] == "log:error"
    assert session.events[2] == "commit"
    assert session.events[3] == "rollback"
