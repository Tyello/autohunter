from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any, Optional, Dict, Iterable
import uuid

from sqlalchemy.orm import Session

from app.models.system_log import SystemLog
from app.utils.fingerprint import compute_fingerprint
from app.core.settings import settings


def _truthy(v: str | None) -> bool:
    if not v:
        return False
    return v.strip().lower() in ("1", "true", "yes", "y", "on")


def _log_stdout_enabled() -> bool:
    return bool(settings.log_stdout)


def _to_json(payload: Optional[Dict[str, Any]]) -> str:
    if payload is None:
        return ""
    try:
        return json.dumps(payload, ensure_ascii=False, default=str)
    except Exception:
        return str(payload)


def log(
    db: Session,
    level: str,
    component: str,
    message: str,
    payload: Optional[Dict[str, Any]] = None,
    *,
    source: Optional[str] = None,
    run_id: Optional[uuid.UUID] = None,
    event_type: Optional[str] = None,
    fingerprint: Optional[str] = None,
    tags: Optional[Iterable[str]] = None,
) -> None:
    """Registra um log no banco (alto volume).

    Importante: **não faz commit**.

    Campos extras (source/event_type/fingerprint/tags) são opcionais, e servem para
    permitir que o Autopilot/agents consultem o DB sem precisar fazer parsing de JSONB.

    Quem chama deve decidir quando commitar/rollback.
    """

    fp = fingerprint
    if event_type and not fp:
        # Use payload as evidence by default (caller can pass a custom fingerprint if needed)
        fp = compute_fingerprint(
            source=source,
            event_type=event_type,
            message=message,
            evidence=payload,
            tags=tags,
        )

    row = SystemLog(
        level=level,
        component=component,
        message=message,
        payload=payload,
        source=source,
        run_id=run_id,
        event_type=event_type,
        fingerprint=fp,
        tags=list(tags) if tags else None,
    )
    db.add(row)

    # opcional: espelha no stdout (pra journalctl)
    if _log_stdout_enabled():
        try:
            ts = datetime.now(timezone.utc).isoformat()
            line = f"{ts} {level} {component} {message}"
            extra = _to_json(payload)
            if extra:
                line += f" {extra}"
            print(line, flush=True)
        except Exception:
            # nunca deixa logging derrubar o processo
            pass
