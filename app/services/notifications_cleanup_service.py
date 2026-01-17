from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.notification import Notification


def cleanup_old_notifications(
    db: Session,
    *,
    keep_suppressed_days: int = 7,
    keep_sent_days: int = 30,
    keep_failed_days: int = 90,
) -> dict:
    """Remove notificacoes antigas para manter a tabela enxuta.

    Regras padrao (simples e seguras):
      - suppressed: 7 dias
      - sent: 30 dias
      - failed: 90 dias
    """
    now = datetime.now(timezone.utc)
    cut_suppressed = now - timedelta(days=keep_suppressed_days)
    cut_sent = now - timedelta(days=keep_sent_days)
    cut_failed = now - timedelta(days=keep_failed_days)

    deleted_suppressed = (
        db.query(Notification)
        .filter(Notification.status == "suppressed")
        .filter(Notification.created_at < cut_suppressed)
        .delete(synchronize_session=False)
    )

    deleted_sent = (
        db.query(Notification)
        .filter(Notification.status == "sent")
        .filter(Notification.sent_at.isnot(None))
        .filter(Notification.sent_at < cut_sent)
        .delete(synchronize_session=False)
    )

    deleted_failed = (
        db.query(Notification)
        .filter(Notification.status == "failed")
        .filter(Notification.created_at < cut_failed)
        .delete(synchronize_session=False)
    )

    db.commit()

    return {
        "deleted_suppressed": int(deleted_suppressed or 0),
        "deleted_sent": int(deleted_sent or 0),
        "deleted_failed": int(deleted_failed or 0),
    }
