from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session

from app.models.system_log import SystemLog


def is_in_cooldown(db: Session, source: str, minutes: int) -> bool:
    """
    Retorna True se houver log recente de bloqueio dessa fonte.
    """
    since = datetime.now(timezone.utc) - timedelta(minutes=minutes)

    row = (
        db.query(SystemLog)
        .filter(SystemLog.component == f"scraper_{source}")
        .filter(SystemLog.level == "warning")
        .filter(SystemLog.message == "source_blocked")
        .filter(SystemLog.created_at >= since)
        .order_by(SystemLog.created_at.desc())
        .first()
    )
    return row is not None
