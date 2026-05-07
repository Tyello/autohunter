from __future__ import annotations

from datetime import datetime, timezone

from app.core.settings import settings
from app.core.shutdown import is_shutdown_requested
from app.db.session import SessionLocal
from app.services.app_kv_service import get_kv, set_kv
from app.services.admin_alerts_service import send_admin_text, iter_admin_chat_ids
from app.services.operational_alerts_service import collect_operational_alerts
from app.services.system_logs_service import log


def _should_log_missing_admin_chat(db) -> bool:
    now = datetime.now(timezone.utc)
    row = get_kv(db, "ops_alert:missing_admin_alert_chat") or {}
    last = row.get("last_sent_at")
    if last:
        try:
            last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
            if (now - last_dt).total_seconds() < 1800:
                return False
        except Exception:
            pass
    set_kv(db, "ops_alert:missing_admin_alert_chat", {"last_sent_at": now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
    return True


def job_admin_monitor() -> None:
    if is_shutdown_requested():
        return
    if not getattr(settings, "admin_monitor_enabled", True):
        return

    with SessionLocal() as db:
        try:
            alerts = collect_operational_alerts(db)
            if alerts and not list(iter_admin_chat_ids()):
                if _should_log_missing_admin_chat(db):
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
