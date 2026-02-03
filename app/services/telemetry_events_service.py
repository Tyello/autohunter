from __future__ import annotations

from typing import Any, Dict, Iterable, Optional
import uuid

from sqlalchemy.orm import Session

from app.models.telemetry_event import TelemetryEvent
from app.utils.fingerprint import compute_fingerprint


def emit_event(
    db: Session,
    *,
    level: str,
    event_type: str,
    source: Optional[str] = None,
    message: Optional[str] = None,
    run_id: Optional[uuid.UUID] = None,
    wishlist_id: Optional[uuid.UUID] = None,
    user_id: Optional[uuid.UUID] = None,
    account_id: Optional[uuid.UUID] = None,
    evidence: Optional[Dict[str, Any]] = None,
    tags: Optional[Iterable[str]] = None,
    fingerprint: Optional[str] = None,
) -> TelemetryEvent:
    """Insert a high-signal telemetry event (no commit)."""

    fp = fingerprint or compute_fingerprint(
        source=source,
        event_type=event_type,
        message=message,
        evidence=evidence,
        tags=tags,
    )

    row = TelemetryEvent(
        level=level,
        source=source,
        run_id=run_id,
        wishlist_id=wishlist_id,
        user_id=user_id,
        account_id=account_id,
        event_type=event_type,
        message=message,
        fingerprint=fp,
        tags=list(tags) if tags else None,
        evidence=evidence,
    )
    db.add(row)
    return row
