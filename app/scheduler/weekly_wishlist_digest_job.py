from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.bot.text_sanitize import sanitize_for_telegram
from app.core.settings import settings
from app.db.session import SessionLocal
from app.notifications.weekly_wishlist_digest_formatter import format_weekly_wishlist_digest
from app.services.app_kv_service import get_kv, set_kv
from app.services.http_session import get_shared_session
from app.services.system_logs_service import log
from app.services.weekly_wishlist_digest_service import WeeklyWishlistDigestService

KV_KEY = "weekly_wishlist_digest:last_run"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _target_tz() -> ZoneInfo:
    try:
        return ZoneInfo(getattr(settings, "default_user_timezone", "America/Sao_Paulo"))
    except Exception:
        return ZoneInfo("America/Sao_Paulo")


def _local_date_key(now_utc: datetime) -> str:
    return now_utc.astimezone(_target_tz()).strftime("%Y-%m-%d")


def _send_text(chat_id: int, text: str) -> None:
    token = settings.telegram_bot_token
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN não configurado")

    msg = sanitize_for_telegram((text or "").strip())
    if not msg:
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    resp = get_shared_session("telegram").post(
        url,
        data={"chat_id": chat_id, "text": msg, "disable_web_page_preview": True},
        timeout=20,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"Telegram API error {resp.status_code}: {resp.text}")


def job_weekly_wishlist_digest() -> None:
    if not getattr(settings, "telegram_enabled", True):
        return

    now = _now_utc()
    local_now = now.astimezone(_target_tz())
    # Safety guard to avoid accidental sends on manual runs outside Saturday.
    if local_now.weekday() != 5:
        return

    with SessionLocal() as db:
        last = get_kv(db, KV_KEY) or {}
        date_key = _local_date_key(now)
        if last.get("sent_for_date") == date_key:
            log(db, "info", "weekly_wishlist_digest", "weekly digest skipped: already sent", {"date": date_key})
            db.commit()
            return

        service = WeeklyWishlistDigestService(db)
        digests = service.build_all_digests()

        users_processed = len(digests)
        wishlists_included = sum(len(d.wishlists) for d in digests)
        digests_sent = 0
        send_failures = 0

        for digest in digests:
            chunks = format_weekly_wishlist_digest(digest, max_chars=int(getattr(settings, "safe_chunk", 3800) or 3800))
            try:
                for chunk in chunks:
                    _send_text(digest.telegram_chat_id, chunk)
                digests_sent += 1
            except Exception as exc:
                send_failures += 1
                log(
                    db,
                    "error",
                    "weekly_wishlist_digest",
                    "weekly digest send failed",
                    {
                        "user_id": str(digest.user_id),
                        "chat_id": digest.telegram_chat_id,
                        "error": f"{type(exc).__name__}: {exc}",
                    },
                )

        set_kv(
            db,
            KV_KEY,
            {
                "sent_for_date": date_key,
                "sent_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "users_processed": users_processed,
                "wishlists_included": wishlists_included,
                "digests_sent": digests_sent,
                "send_failures": send_failures,
            },
        )

        log(
            db,
            "info",
            "weekly_wishlist_digest",
            "weekly digest finished",
            {
                "date": date_key,
                "users_processed": users_processed,
                "wishlists_included": wishlists_included,
                "digests_sent": digests_sent,
                "send_failures": send_failures,
            },
        )
        db.commit()
