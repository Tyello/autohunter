import json
import tempfile
from pathlib import Path

from app.core.settings import settings
from app.db.session import SessionLocal
from app.models.fipe_update_run import FipeUpdateRun
from app.services.fipe_api_client import FipeApiClient
from app.services.fipe_catalog_crawler import crawl_latest_fipe_prices
from app.services.fipe_update_job_service import run_audited_monthly_fipe_update


def run_monthly_fipe_update_once(*, limit_brands: int | None = None) -> FipeUpdateRun:
    static_path = getattr(settings, "fipe_monthly_update_input_path", None)
    if static_path:
        with SessionLocal() as db:
            return run_audited_monthly_fipe_update(db)

    rows = crawl_latest_fipe_prices(FipeApiClient(), limit_brands=limit_brands)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as tmp:
        json.dump(rows, tmp)
        temp_path = Path(tmp.name)

    try:
        with SessionLocal() as db:
            return run_audited_monthly_fipe_update(db, input_path=temp_path)
    finally:
        temp_path.unlink(missing_ok=True)


def job_monthly_fipe_update() -> None:
    try:
        run_monthly_fipe_update_once()
    except Exception as exc:
        print(f"[fipe_update_job] suppressed_exception exc_type={type(exc).__name__} err={exc}")
