from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import text

from app.core.settings import settings
from app.db.session import SessionLocal
from app.services.system_logs_service import log


def job_compute_market_stats_daily():
    """Compute cohort market stats once per day.

    Designed to run on Raspberry Pi:
    - 1 SQL query doing GROUP BY + percentiles in Postgres
    - windowed by recent data to avoid scanning years of history
    """

    window_days = int(getattr(settings, "market_stats_window_days", 180) or 180)
    window_days = max(30, min(window_days, 730))

    with SessionLocal() as db:
        t0 = datetime.now(timezone.utc)
        try:
            sql = text(
                """
                INSERT INTO market_stats_cohorts (
                    make, model, year,
                    median_price, p25_price, p75_price,
                    sample_size, computed_at,
                    created_at, updated_at
                )
                SELECT
                    lower(make) as make,
                    lower(model) as model,
                    year,
                    percentile_cont(0.50) WITHIN GROUP (ORDER BY price) AS median_price,
                    percentile_cont(0.25) WITHIN GROUP (ORDER BY price) AS p25_price,
                    percentile_cont(0.75) WITHIN GROUP (ORDER BY price) AS p75_price,
                    count(*)::int AS sample_size,
                    now() AS computed_at,
                    now() AS created_at,
                    now() AS updated_at
                FROM car_listings
                WHERE
                    price IS NOT NULL
                    AND make IS NOT NULL AND make <> ''
                    AND model IS NOT NULL AND model <> ''
                    AND year IS NOT NULL
                    AND COALESCE(is_sold, false) = false
                    AND created_at >= (now() - (:window_days || ' days')::interval)
                GROUP BY lower(make), lower(model), year
                ON CONFLICT (make, model, year)
                DO UPDATE SET
                    median_price = EXCLUDED.median_price,
                    p25_price = EXCLUDED.p25_price,
                    p75_price = EXCLUDED.p75_price,
                    sample_size = EXCLUDED.sample_size,
                    computed_at = EXCLUDED.computed_at,
                    updated_at = now();
                """
            )
            db.execute(sql, {"window_days": window_days})
            db.commit()

            dt_ms = int((datetime.now(timezone.utc) - t0).total_seconds() * 1000)
            log(db, "info", "market_stats", "daily_compute_ok", {"window_days": window_days, "ms": dt_ms})
            db.commit()
        except Exception as e:
            db.rollback()
            dt_ms = int((datetime.now(timezone.utc) - t0).total_seconds() * 1000)
            try:
                log(db, "error", "market_stats", "daily_compute_failed", {"error": str(e)[:500], "window_days": window_days, "ms": dt_ms})
                db.commit()
            except Exception as mark_exc:
                log(db, "warn", "market_stats", "suppressed_exception", {"stage": "worker.mark_failed", "exc_type": type(mark_exc).__name__, "message": str(mark_exc)[:240], "impact": "job_status_may_stay_running", "fallback": "worker_continues"})
                db.commit()
