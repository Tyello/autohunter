from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional, Dict

from sqlalchemy.orm import Session

from app.models.app_kv import AppKV


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def get_kv(db: Session, key: str) -> Optional[Dict[str, Any]]:
    row = db.query(AppKV).filter(AppKV.key == key).first()
    return row.value if row else None


def set_kv(db: Session, key: str, value: Optional[Dict[str, Any]]) -> None:
    row = db.query(AppKV).filter(AppKV.key == key).first()
    if not row:
        row = AppKV(key=key, value=value)
        db.add(row)
    else:
        row.value = value
        row.updated_at = _utcnow()
    db.commit()
