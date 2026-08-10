from __future__ import annotations


class _FakeScheduler:
    def __init__(self, *args, **kwargs):
        self.jobs = []
        self.init_kwargs = kwargs

    def add_job(self, func, trigger, **kwargs):
        self.jobs.append({"func": func, "trigger": trigger, **kwargs})

    def start(self):
        return None


def test_start_scheduler_registers_monthly_fipe_update_job(monkeypatch):
    from app.scheduler import run as run_mod

    monkeypatch.setattr(run_mod, "BackgroundScheduler", _FakeScheduler)
    monkeypatch.setattr(run_mod, "list_sources", lambda: [])
    monkeypatch.setattr(run_mod.settings, "autopilot_enabled", False)
    monkeypatch.setattr(run_mod.settings, "autopilot_daily_digest_enabled", False)
    monkeypatch.setattr(run_mod.settings, "playwright_smoke_on_boot", False)

    sched = run_mod.start_scheduler()

    jobs = [j for j in sched.jobs if j.get("id") == "monthly_fipe_update"]
    assert len(jobs) == 1
    assert jobs[0]["trigger"] == "cron"
    assert jobs[0]["max_instances"] == 1
    assert jobs[0]["coalesce"] is True


def test_monthly_fipe_update_uses_dedicated_executor(monkeypatch):
    from app.scheduler import run as run_mod

    monkeypatch.setattr(run_mod, "BackgroundScheduler", _FakeScheduler)
    monkeypatch.setattr(run_mod, "list_sources", lambda: [])
    monkeypatch.setattr(run_mod.settings, "autopilot_enabled", False)
    monkeypatch.setattr(run_mod.settings, "autopilot_daily_digest_enabled", False)
    monkeypatch.setattr(run_mod.settings, "playwright_smoke_on_boot", False)

    sched = run_mod.start_scheduler()

    assert "fipe" in sched.init_kwargs.get("executors", {})

    jobs = [j for j in sched.jobs if j.get("id") == "monthly_fipe_update"]
    assert len(jobs) == 1
    assert jobs[0]["executor"] == "fipe"
