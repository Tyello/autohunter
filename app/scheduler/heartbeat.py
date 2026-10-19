from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.services.system_logs_service import log, should_log_throttled

# O job roda a cada 10s (liveness do processo); gravar 1x/min basta (leitores toleram >=5 min).
HEARTBEAT_LOG_INTERVAL_S = 60.0


def heartbeat(db: Session) -> None:
    if not should_log_throttled("scheduler:heartbeat", HEARTBEAT_LOG_INTERVAL_S):
        return
    log(db, "info", "scheduler", "heartbeat", {"ts": datetime.now(timezone.utc).isoformat()})
