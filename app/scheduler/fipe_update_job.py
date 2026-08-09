from app.db.session import SessionLocal
from app.services.fipe_update_job_service import run_audited_monthly_fipe_update


def job_monthly_fipe_update() -> None:
    with SessionLocal() as db:
        run_audited_monthly_fipe_update(db)
