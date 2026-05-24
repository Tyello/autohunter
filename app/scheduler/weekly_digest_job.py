from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.bot.text_sanitize import sanitize_for_telegram
from app.services.http_session import get_shared_session
from app.bot.weekly_digest_renderer import render_weekly_digest
from app.core.settings import settings
from app.db.session import SessionLocal
from app.models.user import User
from app.services.system_logs_service import log
from app.services.weekly_digest_preferences_service import list_digest_enabled_users
from app.services.weekly_digest_service import build_weekly_digest_for_user


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)




def _send_digest_text(chat_id: int, text: str) -> None:
    token = settings.telegram_bot_token
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN não configurado")
    msg = sanitize_for_telegram((text or "").strip())
    if not msg:
        raise RuntimeError("digest vazio")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    resp = get_shared_session("telegram").post(url, data={"chat_id": chat_id, "text": msg, "disable_web_page_preview": True}, timeout=20)
    if resp.status_code >= 400:
        raise RuntimeError(f"Telegram API error {resp.status_code}: {resp.text}")

def _is_recent(pref, now: datetime) -> bool:
    if not pref.last_digest_sent_at:
        return False
    min_window = max(1, int(pref.digest_days or 7))
    return pref.last_digest_sent_at > (now - timedelta(days=min_window))


def run_weekly_digest_once(*, dry_run: bool | None = None) -> dict:
    run_dry = bool(getattr(settings, "weekly_digest_dry_run", True) if dry_run is None else dry_run)
    batch_size = max(1, int(getattr(settings, "weekly_digest_batch_size", 20) or 20))
    max_send = max(1, int(getattr(settings, "weekly_digest_max_send_per_run", 20) or 20))
    now = _now_utc()
    stats = {"checked": 0, "eligible": 0, "sent": 0, "skipped_recent": 0, "skipped_empty": 0, "failed": 0, "dry_run": run_dry}

    with SessionLocal() as db:
        try:
            prefs = list_digest_enabled_users(db, limit=batch_size)
            stats["checked"] = len(prefs)

            for pref in prefs:
                user = db.query(User).filter(User.id == pref.user_id).first()
                if not user or not user.is_active or not user.telegram_chat_id:
                    continue
                if _is_recent(pref, now):
                    stats["skipped_recent"] += 1
                    continue
                if stats["sent"] >= max_send:
                    break

                stats["eligible"] += 1
                payload = build_weekly_digest_for_user(db, user_id=user.id, days=int(pref.digest_days or 7), limit=int(pref.digest_limit or 10))
                if int(((payload or {}).get("totals") or {}).get("sent") or 0) <= 0:
                    stats["skipped_empty"] += 1
                    continue

                try:
                    if not run_dry:
                        _send_digest_text(user.telegram_chat_id, render_weekly_digest(payload))
                        pref.last_digest_sent_at = now
                        db.commit()
                    stats["sent"] += 1
                except Exception as exc:
                    db.rollback()
                    stats["failed"] += 1
                    log(db, "error", "weekly_digest", "send failed", {"user_id": str(user.id), "chat_id": user.telegram_chat_id, "error": f"{type(exc).__name__}: {exc}"})
                    db.commit()

            log(db, "info", "weekly_digest", "job completed", stats)
            db.commit()
            return stats
        except Exception as exc:
            db.rollback()
            log(db, "error", "weekly_digest", "job failed", {"error": f"{type(exc).__name__}: {exc}", **stats})
            db.commit()
            return stats


def job_weekly_digest() -> None:
    if not bool(getattr(settings, "weekly_digest_job_enabled", False)):
        return
    run_weekly_digest_once(dry_run=None)
