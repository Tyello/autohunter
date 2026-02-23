from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import select

from app.models.source_url_cursor import SourceUrlCursor


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def get_cursor(db: Session, *, source: str, url: str) -> Optional[SourceUrlCursor]:
    src = (source or "").strip().lower()
    u = (url or "").strip()
    if not src or not u:
        return None
    return db.execute(
        select(SourceUrlCursor).where(SourceUrlCursor.source == src, SourceUrlCursor.url == u)
    ).scalar_one_or_none()


def touch_cursor(
    db: Session,
    *,
    source: str,
    url: str,
    last_external_id: Optional[str] = None,
    seen_at: Optional[datetime] = None,
) -> SourceUrlCursor:
    """Upsert a cursor row (no commit).

    - Always updates last_checked_at and increments runs.
    - Updates last_external_id/last_seen_at when provided.
    """
    src = (source or "").strip().lower()
    u = (url or "").strip()
    if not src or not u:
        raise ValueError("source/url required")

    row = get_cursor(db, source=src, url=u)
    now = _utcnow()
    if not row:
        row = SourceUrlCursor(source=src, url=u)
        db.add(row)

    row.last_checked_at = now
    row.runs = int(row.runs or 0) + 1

    if last_external_id:
        row.last_external_id = str(last_external_id)
        row.last_seen_at = seen_at or now

    db.flush()
    return row
