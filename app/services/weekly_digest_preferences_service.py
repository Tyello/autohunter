from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.user_digest_preference import UserDigestPreference


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _validate_days(days: int) -> int:
    value = int(days)
    if value < 1 or value > 30:
        raise ValueError("digest_days must be between 1 and 30")
    return value


def _validate_limit(limit: int) -> int:
    value = int(limit)
    if value < 1 or value > 20:
        raise ValueError("digest_limit must be between 1 and 20")
    return value


def get_digest_preference(db: Session, user_id: UUID) -> UserDigestPreference | None:
    return db.query(UserDigestPreference).filter(UserDigestPreference.user_id == user_id).first()


def get_or_create_digest_preference(db: Session, user_id: UUID) -> UserDigestPreference:
    pref = get_digest_preference(db, user_id)
    if pref:
        return pref
    pref = UserDigestPreference(user_id=user_id, weekly_digest_enabled=False, digest_days=7, digest_limit=10)
    db.add(pref)
    db.commit()
    db.refresh(pref)
    return pref


def set_weekly_digest_enabled(db: Session, user_id: UUID, enabled: bool) -> UserDigestPreference:
    pref = get_or_create_digest_preference(db, user_id)
    pref.weekly_digest_enabled = bool(enabled)
    db.commit()
    db.refresh(pref)
    return pref


def update_weekly_digest_preferences(db: Session, user_id: UUID, *, enabled: bool | None = None, days: int | None = None, limit: int | None = None) -> UserDigestPreference:
    pref = get_or_create_digest_preference(db, user_id)
    if enabled is not None:
        pref.weekly_digest_enabled = bool(enabled)
    if days is not None:
        pref.digest_days = _validate_days(days)
    if limit is not None:
        pref.digest_limit = _validate_limit(limit)
    db.commit()
    db.refresh(pref)
    return pref


def list_digest_enabled_users(db: Session, *, limit: int = 100) -> list[UserDigestPreference]:
    safe_limit = max(1, min(1000, int(limit or 100)))
    return (
        db.query(UserDigestPreference)
        .filter(UserDigestPreference.weekly_digest_enabled.is_(True))
        .order_by(UserDigestPreference.updated_at.desc())
        .limit(safe_limit)
        .all()
    )


def mark_digest_previewed(db: Session, user_id: UUID, *, create_if_missing: bool = True) -> UserDigestPreference | None:
    pref = get_digest_preference(db, user_id)
    if not pref and create_if_missing:
        pref = get_or_create_digest_preference(db, user_id)
    if not pref:
        return None
    pref.last_digest_previewed_at = _now()
    db.commit()
    db.refresh(pref)
    return pref
