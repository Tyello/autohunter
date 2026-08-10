from __future__ import annotations


class _FakeScheduler:
    def __init__(self, *args, **kwargs):
        self.jobs = []
        self.init_kwargs = kwargs

    def add_job(self, func, trigger, **kwargs):
        self.jobs.append({"func": func, "trigger": trigger, **kwargs})

    def start(self):
        return None


class _FakeSQLAlchemyJobStore:
    def __init__(self, *args, **kwargs):
        self.init_kwargs = kwargs


def _patch_boot(monkeypatch, run_mod):
    monkeypatch.setattr(run_mod, "BackgroundScheduler", _FakeScheduler)
    monkeypatch.setattr(run_mod, "SQLAlchemyJobStore", _FakeSQLAlchemyJobStore)
    monkeypatch.setattr(run_mod, "list_sources", lambda: [])
    monkeypatch.setattr(run_mod.settings, "autopilot_enabled", False)
    monkeypatch.setattr(run_mod.settings, "autopilot_daily_digest_enabled", False)
    monkeypatch.setattr(run_mod.settings, "playwright_smoke_on_boot", False)


def test_scheduler_uses_sqlalchemy_jobstore(monkeypatch):
    from app.scheduler import run as run_mod

    _patch_boot(monkeypatch, run_mod)

    sched = run_mod.start_scheduler()

    jobstores = sched.init_kwargs.get("jobstores")
    assert jobstores is not None
    assert "default" in jobstores
    assert isinstance(jobstores["default"], _FakeSQLAlchemyJobStore)


def test_jobstore_url_matches_database_url(monkeypatch):
    from app.scheduler import run as run_mod

    monkeypatch.setattr(run_mod.settings, "database_url", "postgresql://fake/db")
    _patch_boot(monkeypatch, run_mod)

    sched = run_mod.start_scheduler()

    jobstore = sched.init_kwargs["jobstores"]["default"]
    assert jobstore.init_kwargs.get("url") == "postgresql://fake/db"
