from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional, Any, Dict

from sqlalchemy.orm import Session
from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import insert

from app.core.settings import settings
from app.models.scrape_job import ScrapeJob


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def count_active_jobs(db: Session, *, queue: str = "browser") -> int:
    return int(
        db.execute(
            select(func.count()).select_from(ScrapeJob).where(
                ScrapeJob.queue == queue,
                ScrapeJob.status.in_(["queued", "running"]),
            )
        ).scalar_one()
    )


def enqueue_job(
    db: Session,
    *,
    source: str,
    queue: str = "browser",
    run_at: Optional[datetime] = None,
    priority: int = 0,
    max_attempts: int = 3,
) -> bool:
    """Enfileira um job (dedupe por (source, queue) enquanto ativo).

    Retorna True se inseriu; False se já existia job ativo.
    """
    src = (source or "").strip().lower()
    if not src:
        return False

    if run_at is None:
        run_at = _utcnow()

    # Hard cap para não explodir memória/DB em máquinas pequenas.
    if queue == "browser":
        cap = int(getattr(settings, "playwright_queue_max_jobs", 25) or 25)
        if cap > 0 and count_active_jobs(db, queue=queue) >= cap:
            return False


    if queue == "http":
        cap = int(getattr(settings, "http_queue_max_jobs", 200) or 200)
        if cap > 0 and count_active_jobs(db, queue=queue) >= cap:
            return False

    stmt = (
        insert(ScrapeJob)
        .values(
            source=src,
            queue=queue,
            run_at=run_at,
            priority=int(priority or 0),
            status="queued",
            attempt=0,
            max_attempts=int(max_attempts or 3),
        )
        .on_conflict_do_nothing(
            index_elements=["source", "queue"],
            index_where=(ScrapeJob.status.in_(["queued", "running"])),
        )
    )

    res = db.execute(stmt)
    # rowcount==1 => inseriu
    return bool(getattr(res, "rowcount", 0) == 1)


def dequeue_next_job(
    db: Session,
    *,
    queue: str = "browser",
    lock_owner: str = "worker",
) -> Optional[ScrapeJob]:
    """Pega o próximo job da fila (FIFO por run_at/created_at).

    Usa FOR UPDATE SKIP LOCKED para suportar múltiplos workers (se quiser no futuro).
    """
    now = _utcnow()

    q = (
        select(ScrapeJob)
        .where(
            ScrapeJob.queue == queue,
            ScrapeJob.status == "queued",
            ScrapeJob.run_at <= now,
        )
        .order_by(ScrapeJob.run_at.asc(), ScrapeJob.priority.desc(), ScrapeJob.created_at.asc())
        .with_for_update(skip_locked=True)
        .limit(1)
    )

    job = db.execute(q).scalar_one_or_none()
    if not job:
        return None

    job.status = "running"
    job.lock_owner = lock_owner
    job.locked_at = now
    job.started_at = now
    return job


def mark_done(
    job: ScrapeJob,
    *,
    result_status: str,
    payload: Optional[Dict[str, Any]] = None,
    duration_ms: Optional[int] = None,
) -> None:
    now = _utcnow()
    job.status = "done"
    job.finished_at = now
    job.result_status = result_status
    job.result_payload = payload
    if duration_ms is not None:
        job.duration_ms = int(duration_ms)


def mark_failed(job: ScrapeJob, *, error: str, retry_in_seconds: int = 60) -> None:
    now = _utcnow()
    job.attempt = int(job.attempt or 0) + 1
    job.error = (error or "")[:800]
    job.finished_at = now

    if int(job.attempt) < int(job.max_attempts or 3):
        # requeue
        job.status = "queued"
        job.run_at = now + timedelta(seconds=max(5, int(retry_in_seconds or 60)))
        job.lock_owner = None
        job.locked_at = None
        job.started_at = None
    else:
        job.status = "failed"
