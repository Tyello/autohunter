from __future__ import annotations

from datetime import datetime, timezone
import json
import threading
import time
from typing import Any, Optional, Dict, Iterable
import uuid

from sqlalchemy.orm import Session

from app.models.system_log import SystemLog
from app.utils.fingerprint import compute_fingerprint
from app.core.settings import settings


_LEVEL_RANK = {"debug": 10, "info": 20, "warn": 30, "warning": 30, "error": 40, "critical": 50}


def _log_stdout_enabled() -> bool:
    return bool(settings.log_stdout)


def _level_passes_stdout(level: str) -> bool:
    """True se `level` atinge o minimo configurado em `log_stdout_min_level`.

    Nivel desconhecido passa (nao esconder sinal); minimo invalido cai em debug.
    """
    minimum = _LEVEL_RANK.get(str(settings.log_stdout_min_level or "").strip().lower(), 10)
    return _LEVEL_RANK.get(str(level or "").strip().lower(), minimum) >= minimum


def _to_json(payload: Optional[Dict[str, Any]]) -> str:
    if payload is None:
        return ""
    try:
        return json.dumps(payload, ensure_ascii=False, default=str)
    except Exception:
        return str(payload)


_throttle_lock = threading.Lock()
_throttle_last: Dict[str, float] = {}


def should_log_throttled(key: str, min_interval_s: float) -> bool:
    """True no maximo 1x a cada `min_interval_s` por `key` (por processo).

    Para logs de rotina de alta frequencia (heartbeat, "job ok" ocioso): evita encher
    `system_logs` sem perder o sinal de vida. Falhas/eventos relevantes nao devem usar isto.
    """
    now = time.monotonic()
    with _throttle_lock:
        last = _throttle_last.get(key)
        if last is not None and now - last < min_interval_s:
            return False
        _throttle_last[key] = now
        return True


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
    if _log_stdout_enabled() and _level_passes_stdout(level):
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
