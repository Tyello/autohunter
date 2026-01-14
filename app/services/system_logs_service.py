from typing import Any, Optional, Dict
from sqlalchemy.orm import Session

from app.models.system_log import SystemLog


def log(db: Session, level: str, component: str, message: str, payload: Optional[Dict[str, Any]] = None) -> None:
    row = SystemLog(level=level, component=component, message=message, payload=payload)
    db.add(row)
    db.commit()
