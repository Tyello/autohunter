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
    groups: Optional[int] = None,
    wishlists: Optional[int] = None,
    items_found: Optional[int] = None,
    items_ingested: Optional[int] = None,
    items_matched: Optional[int] = None,
    notifications_queued: Optional[int] = None,
    proxy_server: Optional[str] = None,
    browser_fallback_enabled: Optional[bool] = None,
    force_browser: Optional[bool] = None,
    error: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> SourceRun:
    """Insert a SourceRun row (no commit).

    Returns the ORM row so callers can link telemetry events via run_id.
    """
    row = SourceRun(
        source=source,
        kind=kind,
        status=status,
        query=query,
        url=url,
        duration_ms=duration_ms,
        http_status=http_status,
        groups=groups,
        wishlists=wishlists,
        items_found=items_found,
        items_ingested=items_ingested,
        items_matched=items_matched,
        notifications_queued=notifications_queued,
        proxy_server=proxy_server,
        browser_fallback_enabled=browser_fallback_enabled,
        force_browser=force_browser,
        error=error,
        payload=payload,
    )
    db.add(row)
    # Flush so row.id is available immediately (still no commit).
    db.flush()
    return row
