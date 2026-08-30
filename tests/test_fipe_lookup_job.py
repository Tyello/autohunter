from contextlib import contextmanager

from app.scheduler.fipe_lookup_job import job_process_fipe_lookups


class _FakeDB:
    def __init__(self):
        self.committed = False

    def commit(self):
        self.committed = True


class _SessionCtx:
    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self.db

    def __exit__(self, exc_type, exc, tb):
        return False


def test_job_runs_process_pending_logs_and_commits(monkeypatch):
    db = _FakeDB()

    @contextmanager
    def mock_session_scope():
        yield db

    monkeypatch.setattr(
        "app.scheduler.fipe_lookup_job.session_scope",
        mock_session_scope,
    )
    monkeypatch.setattr(
        "app.scheduler.fipe_lookup_job.process_pending_fipe_lookups",
        lambda _db: {"claimed": 2, "done": 1, "skipped": 0, "refreshed": 1, "failed_temp": 0, "failed_final": 0},
    )
    logged = []
    monkeypatch.setattr(
        "app.scheduler.fipe_lookup_job.log",
        lambda db_arg, level, component, message, payload: logged.append((level, component, message, payload)),
    )

    job_process_fipe_lookups()

    assert db.committed is True
    assert len(logged) == 1
    level, component, message, payload = logged[0]
    assert level == "info"
    assert component == "fipe_lookup"
    assert payload["claimed"] == 2


def test_job_logs_error_and_still_commits_on_failure(monkeypatch):
    db = _FakeDB()

    @contextmanager
    def mock_session_scope():
        yield db

    monkeypatch.setattr(
        "app.scheduler.fipe_lookup_job.session_scope",
        mock_session_scope,
    )

    def boom(_db):
        raise RuntimeError("db unreachable")

    monkeypatch.setattr(
        "app.scheduler.fipe_lookup_job.process_pending_fipe_lookups",
        boom,
    )
    logged = []
    monkeypatch.setattr(
        "app.scheduler.fipe_lookup_job.log",
        lambda db_arg, level, component, message, payload: logged.append((level, message, payload)),
    )

    job_process_fipe_lookups()

    assert db.committed is True
    assert logged[0][0] == "error"
    assert "db unreachable" in logged[0][2]["error"]
