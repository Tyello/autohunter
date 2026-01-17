from __future__ import annotations

from typing import Any, Optional, Dict

from sqlalchemy.orm import Session

from app.models.source_run import SourceRun


def record_run(
    db: Session,
    *,
    source: str,
    kind: str,
    status: str,
    query: Optional[str] = None,
    url: Optional[str] = None,
    duration_ms: Optional[int] = None,
    http_status: Optional[int] = None,
    items_found: Optional[int] = None,
    items_ingested: Optional[int] = None,
    items_matched: Optional[int] = None,
    notifications_queued: Optional[int] = None,
    error: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> None:
    row = SourceRun(
        source=source,
        kind=kind,
        status=status,
        query=query,
        url=url,
        duration_ms=duration_ms,
        http_status=http_status,
        items_found=items_found,
        items_ingested=items_ingested,
        items_matched=items_matched,
        notifications_queued=notifications_queued,
        error=error,
        payload=payload,
    )
    db.add(row)
    # Commit fica por conta do chamador.
