import json
import tempfile
from pathlib import Path

from app.core.settings import settings
from app.db.session import session_scope
from app.models.fipe_update_run import FipeUpdateRun
from app.services.fipe_api_client import FipeApiClient
from app.services.fipe_catalog_crawler import crawl_latest_fipe_prices
from app.services.fipe_rate_limiter import FipeRateLimiter
from app.services.fipe_update_job_service import run_audited_monthly_fipe_update


def run_monthly_fipe_update_once(*, limit_brands: int | None = None) -> FipeUpdateRun:
    static_path = getattr(settings, "fipe_monthly_update_input_path", None)
    if static_path:
        with session_scope() as db:
            return run_audited_monthly_fipe_update(db)

    shared_rate_limiter = FipeRateLimiter(
        rate_limit_ms=settings.fipe_api_rate_limit_ms,
        max_throttle_ms=settings.fipe_api_max_throttle_ms,
        recovery_after_successes=settings.fipe_throttle_recovery_after_successes,
    )
    rows = crawl_latest_fipe_prices(
        client_factory=lambda: FipeApiClient(rate_limiter=shared_rate_limiter),
        limit_brands=limit_brands,
        concurrency=settings.fipe_crawler_concurrency,
    )

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as tmp:
        json.dump(rows, tmp)
        temp_path = Path(tmp.name)

    try:
        with session_scope() as db:
            return run_audited_monthly_fipe_update(db, input_path=temp_path)
    finally:
        temp_path.unlink(missing_ok=True)


def job_monthly_fipe_update() -> None:
    try:
        run_monthly_fipe_update_once()
    except Exception as exc:
        print(f"[fipe_update_job] suppressed_exception exc_type={type(exc).__name__} err={exc}")
