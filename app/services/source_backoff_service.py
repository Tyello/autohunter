from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, Any, Dict

from sqlalchemy.orm import Session

from app.core.settings import settings
from app.models.source_state import SourceState


@dataclass
class Availability:
    is_allowed: bool
    reason: Optional[str] = None
    next_allowed_at: Optional[datetime] = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _get_or_create_state(db: Session, source: str) -> SourceState:
    row = db.query(SourceState).filter(SourceState.source == source).first()
    if row:
        return row
    row = SourceState(source=source)
    db.add(row)
    db.flush()  # garante id
    return row


def is_source_allowed(db: Session, source: str) -> Availability:
    """Retorna se a fonte pode rodar agora (considera backoff)."""
    st = _get_or_create_state(db, source)
    if st.next_allowed_at and st.next_allowed_at > _utcnow():
        return Availability(is_allowed=False, reason="backoff", next_allowed_at=st.next_allowed_at)
    return Availability(is_allowed=True)


def _compute_backoff_minutes(base_minutes: int, exponent: int) -> int:
    """Backoff exponencial com teto."""
    base = max(1, int(base_minutes or 1))
    # 1,2,4,8... * base
    minutes = base * (2 ** max(0, exponent - 1))
    max_m = int(getattr(settings, "source_backoff_max_minutes", 720) or 720)
    return int(min(minutes, max_m))


def mark_success(db: Session, source: str, *, rate_limit_seconds: int = 0, payload: Optional[Dict[str, Any]] = None) -> None:
    st = _get_or_create_state(db, source)
    st.last_run_at = _utcnow()
    st.consecutive_blocks = 0
    st.consecutive_failures = 0

    # Apply throttling (min interval) using next_allowed_at.
    rl = int(rate_limit_seconds or 0)
    if rl > 0:
        st.next_allowed_at = _utcnow() + timedelta(seconds=rl)
    else:
        st.next_allowed_at = None

    st.last_status = "success"
    st.last_error = None
    st.last_payload = payload
    db.add(st)


def mark_skipped(db: Session, source: str, reason: str, payload: Optional[Dict[str, Any]] = None) -> None:
    st = _get_or_create_state(db, source)
    st.last_run_at = _utcnow()
    st.last_status = f"skipped:{reason}"
    st.last_payload = payload
    db.add(st)


def mark_blocked(
    db: Session,
    source: str,
    *,
    base_cooldown_minutes: int,
    http_status: Optional[int] = None,
    url: Optional[str] = None,
) -> int:
    """Marca bloqueio e retorna minutos de backoff aplicado."""
    st = _get_or_create_state(db, source)
    st.last_run_at = _utcnow()
    st.consecutive_blocks = int(st.consecutive_blocks or 0) + 1
    st.consecutive_failures = 0

    minutes = _compute_backoff_minutes(base_cooldown_minutes, st.consecutive_blocks)
    jitter_s = int(getattr(settings, "source_backoff_jitter_seconds", 20) or 20)
    st.next_allowed_at = _utcnow() + timedelta(minutes=minutes, seconds=jitter_s)

    st.last_status = "blocked"
    st.last_error = None
    st.last_payload = {"http_status": http_status, "url": url, "backoff_minutes": minutes}
    db.add(st)
    return minutes


def mark_error(
    db: Session,
    source: str,
    *,
    base_cooldown_minutes: int,
    error: str,
    url: Optional[str] = None,
) -> int:
    """Marca erro e retorna minutos de backoff aplicado."""
    st = _get_or_create_state(db, source)
    st.last_run_at = _utcnow()
    st.consecutive_failures = int(st.consecutive_failures or 0) + 1
    # não zera blocks completamente — mas deixa o signal principal como failure
    st.consecutive_blocks = 0

    minutes = _compute_backoff_minutes(base_cooldown_minutes, st.consecutive_failures)
    jitter_s = int(getattr(settings, "source_backoff_jitter_seconds", 20) or 20)
    st.next_allowed_at = _utcnow() + timedelta(minutes=minutes, seconds=jitter_s)

    st.last_status = "error"
    st.last_error = error[:800]  # evita crescer infinito
    st.last_payload = {"url": url, "backoff_minutes": minutes}
    db.add(st)
    return minutes
