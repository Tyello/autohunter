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
ACTIVE_JOB_CONFLICT_INDEX_NAME = "uq_scrape_jobs_active_source_queue"
ACTIVE_JOB_CONFLICT_LEGACY_INDEX_NAMES = ("ix_scrape_jobs_active_source_queue_unique",)


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


def has_active_source_queue_partial_index(db: Session) -> bool:
    details = get_active_source_queue_partial_index_details(db)
    return bool(details.get("ok", False))


def get_active_source_queue_partial_index_details(db: Session) -> dict[str, Any]:
    def _matches_active_conflict_partial_index(definition: str | None) -> bool:
        normalized = " ".join((definition or "").lower().split())
        checks = [
            "unique index",
            "(source, queue)",
            "where",
            "status",
            "queued",
            "running",
        ]
        return all(token in normalized for token in checks)

    def _name_ok(name: str | None) -> bool:
        n = (name or "").strip().lower()
        allowed = {ACTIVE_JOB_CONFLICT_INDEX_NAME, *ACTIVE_JOB_CONFLICT_LEGACY_INDEX_NAMES}
        return n in {a.lower() for a in allowed}

    bind = db.get_bind()
    if not bind:
        return {"ok": False, "reason": "no_bind"}
    dialect = bind.dialect.name
    if dialect == "postgresql":
        rows = db.execute(
            text(
                """
                select indexname, indexdef
                from pg_indexes
                where schemaname = current_schema()
                  and tablename = 'scrape_jobs'
                """
            )
        ).all()
        for indexname, indexdef in rows:
            if _matches_active_conflict_partial_index(indexdef):
                return {"ok": True, "index_name": indexname, "index_name_ok": _name_ok(indexname), "definition": indexdef}
        return {"ok": False, "reason": "not_found"}

    if dialect == "sqlite":
        rows = db.execute(
            text(
                """
                select name, sql
                from sqlite_master
                where type = 'index'
                  and tbl_name = 'scrape_jobs'
                """
            )
        ).all()
        for name, sql_def in rows:
            if _matches_active_conflict_partial_index(sql_def):
                return {"ok": True, "index_name": name, "index_name_ok": _name_ok(name), "definition": sql_def}
        return {"ok": False, "reason": "not_found"}

    return {"ok": False, "reason": f"unsupported_dialect:{dialect}"}


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
    # Defesa adicional para restart/kill abrupto:
    # running sem locked_at nunca será resgatado pelo filtro acima e pode bloquear
    # novos enqueues indefinidamente por causa do índice parcial de job ativo.
    rows_invalid = (
        db.query(ScrapeJob)
        .filter(ScrapeJob.queue == queue)
        .filter(ScrapeJob.status == "running")
        .filter(ScrapeJob.locked_at.is_(None))
        .all()
    )

    for job in [*rows, *rows_invalid]:
        job.status = "queued"
        job.lock_owner = None
        job.locked_at = None
        job.started_at = None
        job.finished_at = None
        job.run_at = _utcnow() - timedelta(seconds=1)

    return len(rows) + len(rows_invalid)


def scrape_jobs_runtime_snapshot(db: Session, *, now: datetime | None = None, stale_after_seconds: int | None = None) -> dict[str, Any]:
    now = now or _utcnow()
    ttl = int(stale_after_seconds if stale_after_seconds is not None else getattr(settings, "scrape_job_running_ttl_seconds", 900) or 900)
    stale_cut = now - timedelta(seconds=max(60, ttl))
    q = db.query
    return {
        "queued": int(q(func.count(ScrapeJob.id)).filter(ScrapeJob.status == "queued").scalar() or 0),
        "running": int(q(func.count(ScrapeJob.id)).filter(ScrapeJob.status == "running").scalar() or 0),
        "running_stale": int(
            q(func.count(ScrapeJob.id))
            .filter(ScrapeJob.status == "running")
            .filter(
                (ScrapeJob.locked_at.is_(None))
                | (ScrapeJob.locked_at < stale_cut)
            )
            .scalar()
            or 0
        ),
        "last_created_at": q(func.max(ScrapeJob.created_at)).scalar(),
        "last_started_at": q(func.max(ScrapeJob.started_at)).scalar(),
        "last_finished_at": q(func.max(ScrapeJob.finished_at)).scalar(),
    }

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
        db.rollback()
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
