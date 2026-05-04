from __future__ import annotations

from app.core.settings import settings
from app.db.session import SessionLocal
from app.services.admin_alerts_service import send_admin_text, iter_admin_chat_ids
from app.services.operational_alerts_service import collect_operational_alerts
from app.services.system_logs_service import log


def job_admin_monitor() -> None:
    if not getattr(settings, "admin_monitor_enabled", True):
        return

    with SessionLocal() as db:
        try:
            alerts = collect_operational_alerts(db)
            if not list(iter_admin_chat_ids()):
                log(db, "warn", "admin_monitor", "missing_admin_alert_chat", {"hint": "configure autohunter_admin_alert_chats or autohunter_admins"})
                db.commit()
                return
            for alert in alerts:
                try:
                    send_admin_text(alert.message)
                except Exception as e:
                    log(db, "warn", "admin_monitor", "alert_send_failed", {"key": alert.key, "err": str(e)[:160]})
            db.commit()
        except Exception as e:
            log(db, "warn", "admin_monitor", "monitor_failed", {"err": str(e)[:200]})
            db.commit()
