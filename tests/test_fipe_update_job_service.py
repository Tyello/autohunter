from datetime import datetime, timedelta, timezone

from app.models.fipe_update_run import FipeUpdateRun
from app.services.fipe_update_job_service import run_audited_monthly_fipe_update, should_run_monthly_fipe_update


def test_fipe_update_success_audited(db, monkeypatch, tmp_path):
    inp = tmp_path / "fipe.json"; inp.write_text("[]")
    monkeypatch.setattr("app.services.fipe_update_job_service.settings.fipe_monthly_update_enabled", True)
    monkeypatch.setattr("app.services.fipe_update_job_service.run_monthly_fipe_sync", lambda *a, **k: {"catalog_import": {"inserted": 2, "updated": 1}, "price_plan": {"inserted": 3, "updated": 0}})
    run = run_audited_monthly_fipe_update(db, reference_month="2026-05", input_path=inp)
    assert run.status == "completed"
    assert run.updated_rows == 6
    assert run.duration_ms is not None


def test_fipe_update_failure_audited(db, monkeypatch, tmp_path):
    inp = tmp_path / "fipe.json"; inp.write_text("[]")
    monkeypatch.setattr("app.services.fipe_update_job_service.settings.fipe_monthly_update_enabled", True)
    def boom(*a, **k):
        raise RuntimeError("bad fipe")
    monkeypatch.setattr("app.services.fipe_update_job_service.run_monthly_fipe_sync", boom)
    run = run_audited_monthly_fipe_update(db, reference_month="2026-05", input_path=inp)
    assert run.status == "failed"
    assert "bad fipe" in run.error_message


def test_fipe_update_lock_skips_second_execution(db):
    db.add(FipeUpdateRun(started_at=datetime.now(timezone.utc), status="running", lock_key="monthly_fipe_update"))
    db.commit()
    run = run_audited_monthly_fipe_update(db, reference_month="2026-05")
    assert run.status == "skipped"
    assert "lock" in run.error_message


def test_fipe_update_scheduler_based_on_last_success(db, monkeypatch):
    monkeypatch.setattr("app.services.fipe_update_job_service.settings.fipe_monthly_update_min_interval_days", 25)
    fresh = datetime.now(timezone.utc) - timedelta(days=3)
    db.add(FipeUpdateRun(started_at=fresh, finished_at=fresh, status="completed", lock_key="monthly_fipe_update"))
    db.commit()
    assert should_run_monthly_fipe_update(db) is False


def test_fipe_update_scheduler_due_when_last_success_old(db, monkeypatch):
    monkeypatch.setattr("app.services.fipe_update_job_service.settings.fipe_monthly_update_min_interval_days", 25)
    old = datetime.now(timezone.utc) - timedelta(days=40)
    db.add(FipeUpdateRun(started_at=old, finished_at=old, status="completed", lock_key="monthly_fipe_update"))
    db.commit()
    assert should_run_monthly_fipe_update(db) is True


def test_admin_fipe_update_status_renderer():
    from app.bot.admin_handlers_fipe import render_admin_fipe_update_status
    text = render_admin_fipe_update_status({"last": None, "enabled": True, "next_schedule": "monthly day 05 at 05:00 UTC", "due_by_last_success": True})
    assert "FIPE atualização mensal" in text
    assert "Due pelo último sucesso: True" in text
