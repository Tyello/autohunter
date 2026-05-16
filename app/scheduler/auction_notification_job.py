from __future__ import annotations

import asyncio
import threading
from time import perf_counter

from app.core.settings import settings
from app.db.session import SessionLocal
from app.services.auction_notification_job_service import run_auction_notification_job
from app.services.system_logs_service import log

_AUCTION_NOTIFICATION_SCHEDULER_LOCK = threading.Lock()


def _base_payload() -> dict:
    return {
        "enabled": bool(getattr(settings, "auction_notifications_enabled", False)),
        "dry_run": bool(getattr(settings, "auction_notifications_dry_run", True)),
        "max_wishlists": int(getattr(settings, "auction_notifications_max_wishlists_per_run", 20) or 20),
        "max_per_wishlist": int(getattr(settings, "auction_notifications_max_per_wishlist", 1) or 1),
        "max_per_user_per_day": int(getattr(settings, "auction_notifications_max_per_user_per_day", 3) or 3),
    }


def run_scheduled_auction_notification_job(db, bot=None) -> dict:
    payload = _base_payload()
    t0 = perf_counter()
    if not _AUCTION_NOTIFICATION_SCHEDULER_LOCK.acquire(blocking=False):
        out = {"skipped": True, "reason": "already_running", "sent": 0}
        log(db, "info", "scheduler", "auction_notification_scheduler_tick_skipped", {**payload, **out})
        return out

    try:
        log(db, "info", "scheduler", "auction_notification_scheduler_tick_started", payload)
        if not payload["enabled"]:
            out = {"skipped": True, "reason": "disabled", "sent": 0}
            log(db, "info", "scheduler", "auction_notification_job_skipped", {"reason": "disabled"})
            log(db, "info", "scheduler", "auction_notification_scheduler_tick_skipped", {**payload, **out})
            return out

        if not payload["dry_run"] and bot is None:
            out = {"skipped": True, "reason": "bot_unavailable_for_real_send", "sent": 0}
            log(db, "warn", "scheduler", "auction_notification_scheduler_tick_skipped", {**payload, **out})
            return out

        result = asyncio.run(
            run_auction_notification_job(
                db,
                bot=bot if not payload["dry_run"] else None,
                dry_run=payload["dry_run"],
                max_wishlists=payload["max_wishlists"],
                max_per_wishlist=payload["max_per_wishlist"],
                max_per_user_per_day=payload["max_per_user_per_day"],
                source=None,
            )
        )
        out = {**result, "skipped": False}
        return out
    except Exception as exc:
        out = {"skipped": True, "reason": "error", "sent": 0, "errors": 1, "messages": [str(exc)]}
        log(db, "error", "scheduler", "auction_notification_scheduler_tick_failed", {**payload, **out})
        return out
    finally:
        dt = int((perf_counter() - t0) * 1000)
        try:
            # best-effort end log (last known out can be missing in early edge cases)
            final_out = locals().get("out", {"skipped": True, "reason": "unknown", "sent": 0})
            msg = "auction_notification_scheduler_tick_finished"
            if final_out.get("skipped"):
                msg = "auction_notification_scheduler_tick_skipped"
            log(
                db,
                "info",
                "scheduler",
                msg,
                {
                    **payload,
                    "sent": int(final_out.get("sent", 0) or 0),
                    "previews": int(final_out.get("previews", 0) or 0),
                    "skipped_no_match": int(final_out.get("skipped_no_match", 0) or 0),
                    "skipped_duplicate": int(final_out.get("skipped_duplicate", 0) or 0),
                    "skipped_daily_limit": int(final_out.get("skipped_daily_limit", 0) or 0),
                    "errors": int(final_out.get("errors", 0) or 0),
                    "duration_ms": dt,
                    "reason": final_out.get("reason"),
                },
            )
            db.commit()
        except Exception:
            db.rollback()
        _AUCTION_NOTIFICATION_SCHEDULER_LOCK.release()


def job_scheduled_auction_notification(bot=None) -> None:
    with SessionLocal() as db:
        run_scheduled_auction_notification_job(db, bot=bot)
