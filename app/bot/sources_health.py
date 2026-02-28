from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@dataclass(frozen=True)
class DueInfo:
    next_due_at: Optional[datetime]
    late_by_minutes: Optional[int]


def compute_due_info(*, sched_minutes: Optional[int], last_effective_at: Optional[datetime], now: Optional[datetime] = None) -> DueInfo:
    now = _ensure_utc(now) or utcnow()
    last_effective_at = _ensure_utc(last_effective_at)

    if not sched_minutes or sched_minutes <= 0:
        return DueInfo(next_due_at=None, late_by_minutes=None)

    if last_effective_at is None:
        return DueInfo(next_due_at=now, late_by_minutes=0)

    next_due = last_effective_at + timedelta(minutes=int(sched_minutes))
    if now <= next_due:
        return DueInfo(next_due_at=next_due, late_by_minutes=0)

    late_by = int((now - next_due).total_seconds() // 60)
    return DueInfo(next_due_at=next_due, late_by_minutes=late_by)


def fmt_dt(dt: Optional[datetime]) -> str:
    if dt is None:
        return "-"
    dt = _ensure_utc(dt) or dt
    return dt.strftime("%Y-%m-%d %H:%M:%SZ")
