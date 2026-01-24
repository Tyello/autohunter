from typing import Any, Optional, Dict
from sqlalchemy.orm import Session

from app.models.system_log import SystemLog

import os
import json
from datetime import datetime, timezone


def _truthy(v: str | None) -> bool:
    if not v:
        return False
    return v.strip().lower() in ("1", "true", "yes", "y", "on")


def _log_stdout_enabled() -> bool:
    return _truthy(os.getenv("LOG_STDOUT"))


def _to_json(payload: Optional[Dict[str, Any]]) -> str:
    if payload is None:
        return ""
    try:
        return json.dumps(payload, ensure_ascii=False, default=str)
    except Exception:
        return str(payload)


def log(db: Session, level: str, component: str, message: str, payload: Optional[Dict[str, Any]] = None) -> None:
    # 1) sempre persiste no banco (comportamento atual)
    row = SystemLog(level=level, component=component, message=message, payload=payload)
    db.add(row)
    db.commit()

    # 2) opcional: espelha no stdout (pra journalctl)
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