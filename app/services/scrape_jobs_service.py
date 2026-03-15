from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional, Any, Dict

from sqlalchemy.orm import Session
from sqlalchemy import select, func, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import ProgrammingError

from app.core.settings import settings
from app.models.scrape_job import ScrapeJob


ACTIVE_JOB_CONFLICT_COLUMNS = ("source", "queue")
ACTIVE_JOB_CONFLICT_PREDICATE_SQL = "status IN ('queued','running')"


def _is_missing_on_conflict_constraint(exc: ProgrammingError) -> bool:
    orig = getattr(exc, "orig", None)
    msg = str(orig or exc).lower()
    return "no unique or exclusion constraint matching the on conflict specification" in msg


def _build_schema_mismatch_detail(db: Session, *, queue: str) -> str:
    bind = db.get_bind()
    if not bind or bind.dialect.name != "postgresql":
        return "schema snapshot unavailable (dialect is not postgresql)"

    rows = db.execute(
        text(
            """
            select
                i.indexname,
                i.indexdef
            from pg_indexes i
            where i.schemaname = current_schema()
              and i.tablename = 'scrape_jobs'
            order by i.indexname
            """
        )
    ).all()
    indexes = [f"{name}: {definition}" for name, definition in rows]
    rendered = "; ".join(indexes) if indexes else "<no indexes found for scrape_jobs>"
    return (
        f"queue={queue}; expected conflict_target={ACTIVE_JOB_CONFLICT_COLUMNS}; "
        f"expected_predicate={ACTIVE_JOB_CONFLICT_PREDICATE_SQL}; indexes={rendered}"
    )


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)



def requeue_stale_running_jobs(
    db: Session,
    *,
    queue: str,
    stale_after_seconds: int | None = None,
) -> int:
    """Move stale running jobs back to queued so the source is schedulable again."""
    ttl = int(stale_after_seconds if stale_after_seconds is not None else getattr(settings, "scrape_job_running_ttl_seconds", 900) or 900)
    if ttl <= 0:
        return 0

    cutoff = _utcnow() - timedelta(seconds=ttl)
    rows = (
        db.query(ScrapeJob)
        .filter(ScrapeJob.queue == queue)
        .filter(ScrapeJob.status == "running")
        .filter(ScrapeJob.locked_at.isnot(None))
        .filter(ScrapeJob.locked_at < cutoff)
        .all()
    )

    for job in rows:
        job.status = "queued"
        job.lock_owner = None
        job.locked_at = None
        job.started_at = None
        job.finished_at = None
        job.run_at = _utcnow() - timedelta(seconds=1)

    return len(rows)

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
    requeue_stale_running_jobs(db, queue=queue)

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
            index_elements=list(ACTIVE_JOB_CONFLICT_COLUMNS),
            # Importante: usar SQL literal para casar 1:1 com o índice parcial.
            # Com bind params, o PostgreSQL pode falhar inferência com erro
            # "no unique or exclusion constraint matching the ON CONFLICT specification".
            index_where=text(ACTIVE_JOB_CONFLICT_PREDICATE_SQL),
        )
    )

    try:
        res = db.execute(stmt)
    except ProgrammingError as exc:
        if not _is_missing_on_conflict_constraint(exc):
            raise
        detail = _build_schema_mismatch_detail(db, queue=queue)
        raise RuntimeError(
            "scrape_jobs enqueue schema mismatch: "
            f"ON CONFLICT ({', '.join(ACTIVE_JOB_CONFLICT_COLUMNS)}) "
            f"WHERE {ACTIVE_JOB_CONFLICT_PREDICATE_SQL}. {detail}"
        ) from exc

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
    requeue_stale_running_jobs(db, queue=queue)
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
