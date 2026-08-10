from app.scheduler.operational_data_cleanup_job import job_operational_data_cleanup


class _FakeDB:
    def __init__(self):
        self.logged = []
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


def test_job_runs_cleanup_logs_and_commits(monkeypatch):
    db = _FakeDB()
    monkeypatch.setattr(
        "app.scheduler.operational_data_cleanup_job.SessionLocal",
        lambda: _SessionCtx(db),
    )
    monkeypatch.setattr(
        "app.scheduler.operational_data_cleanup_job.run_operational_cleanup",
        lambda _db: {"system_logs": 3, "source_runs": 1},
    )
    logged = []
    monkeypatch.setattr(
        "app.scheduler.operational_data_cleanup_job.log",
        lambda db_arg, level, component, message, payload: logged.append((level, component, message, payload)),
    )

    job_operational_data_cleanup()

    assert db.committed is True
    assert len(logged) == 1
    level, component, message, payload = logged[0]
    assert level == "info"
    assert component == "cleanup"
    assert payload["system_logs"] == 3


def test_job_logs_error_and_still_commits_on_failure(monkeypatch):
    db = _FakeDB()
    monkeypatch.setattr(
        "app.scheduler.operational_data_cleanup_job.SessionLocal",
        lambda: _SessionCtx(db),
    )

    def boom(_db):
        raise RuntimeError("db unreachable")

    monkeypatch.setattr(
        "app.scheduler.operational_data_cleanup_job.run_operational_cleanup",
        boom,
    )
    logged = []
    monkeypatch.setattr(
        "app.scheduler.operational_data_cleanup_job.log",
        lambda db_arg, level, component, message, payload: logged.append((level, message, payload)),
    )

    job_operational_data_cleanup()

    assert db.committed is True
    assert logged[0][0] == "error"
    assert "db unreachable" in logged[0][2]["error"]
