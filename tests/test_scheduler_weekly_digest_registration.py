from __future__ import annotations


class _FakeScheduler:
    def __init__(self, *args, **kwargs):
        self.jobs = []

    def add_job(self, func, trigger, **kwargs):
        self.jobs.append({"func": func, "trigger": trigger, **kwargs})

    def start(self):
        return None


def test_start_scheduler_registers_weekly_digest_job(monkeypatch):
    from app.scheduler import run as run_mod

    monkeypatch.setattr(run_mod, "BackgroundScheduler", _FakeScheduler)
    monkeypatch.setattr(run_mod, "list_sources", lambda: [])
    monkeypatch.setattr(run_mod.settings, "autopilot_enabled", False)
    monkeypatch.setattr(run_mod.settings, "autopilot_daily_digest_enabled", False)

    sched = run_mod.start_scheduler()

    weekly = [j for j in sched.jobs if j.get("id") == "weekly_wishlist_digest"]
    assert len(weekly) == 1
    job = weekly[0]
    assert job["trigger"] == "cron"
    assert job["day_of_week"] == "sat"
    assert job["hour"] == 10
    assert job["minute"] == 0
