from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional


@dataclass(frozen=True)
class SourceStaleness:
    stale: bool
    threshold_minutes: int
    age_minutes: Optional[int]
    overdue_minutes: Optional[int]


def _safe_sched_minutes(sched_minutes: int | None, default_minutes: int = 60) -> int:
    try:
        v = int(sched_minutes or 0)
    except Exception:
        v = 0
    return v if v > 0 else int(default_minutes)


def stale_threshold_minutes(
    sched_minutes: int | None,
    *,
    factor: float = 2.0,
    min_global_minutes: int = 180,
    default_sched_minutes: int = 60,
) -> int:
    sched = _safe_sched_minutes(sched_minutes, default_sched_minutes)
    calc = int(round(float(sched) * float(factor)))
    return max(int(min_global_minutes), calc)


def evaluate_source_staleness(
    *,
    now: datetime,
    last_run_at: Optional[datetime],
    sched_minutes: int | None,
    factor: float = 2.0,
    min_global_minutes: int = 180,
    default_sched_minutes: int = 60,
) -> SourceStaleness:
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    threshold = stale_threshold_minutes(
        sched_minutes,
        factor=factor,
        min_global_minutes=min_global_minutes,
        default_sched_minutes=default_sched_minutes,
    )
    if not last_run_at:
        return SourceStaleness(stale=True, threshold_minutes=threshold, age_minutes=None, overdue_minutes=None)

    if last_run_at.tzinfo is None:
        last_run_at = last_run_at.replace(tzinfo=timezone.utc)

    age_m = max(0, int((now - last_run_at).total_seconds() // 60))
    overdue_m = age_m - threshold
    return SourceStaleness(
        stale=age_m > threshold,
        threshold_minutes=threshold,
        age_minutes=age_m,
        overdue_minutes=overdue_m if overdue_m > 0 else 0,
    )


def heartbeat_is_stale(now: datetime, last_heartbeat_at: Optional[datetime], stale_after_minutes: int = 15) -> bool:
    if not last_heartbeat_at:
        return True
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    if last_heartbeat_at.tzinfo is None:
        last_heartbeat_at = last_heartbeat_at.replace(tzinfo=timezone.utc)
    cutoff = now - timedelta(minutes=int(stale_after_minutes or 15))
    return last_heartbeat_at < cutoff

