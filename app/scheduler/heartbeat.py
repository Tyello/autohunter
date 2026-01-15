from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.services.system_logs_service import log


def heartbeat(db: Session) -> None:
    log(db, "info", "scheduler", "heartbeat", {"ts": datetime.now(timezone.utc).isoformat()})
