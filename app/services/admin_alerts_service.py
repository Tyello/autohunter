from __future__ import annotations

from typing import Iterable, List
import logging

from app.core.settings import settings
from app.bot.text_sanitize import sanitize_for_telegram
from app.services.http_session import get_shared_session


TELEGRAM_TEXT_MAX = 4096
logger = logging.getLogger(__name__)


def _parse_admins(raw: str | None) -> List[int]:
    raw = raw or ""
    out: List[int] = []
    for part in raw.split(","):
        part = (part or "").strip()
        if part.isdigit():
            out.append(int(part))
    return out


def iter_admin_chat_ids() -> Iterable[int]:
    # Preferencialmente envia alertas para chats dedicados (ex.: grupo de admin)
    # para não poluir chats de uso comum.
    raw = getattr(settings, "autohunter_admin_alert_chats", None) or None
    if raw:
        return _parse_admins(raw)
    # compatibilidade: comportamento antigo
    return _parse_admins(settings.autohunter_admins)


def admin_alerts_diagnostic_snapshot() -> dict:
    chats = list(iter_admin_chat_ids())
    return {
        "admin_alerts_enabled": bool(getattr(settings, "admin_alerts_enabled", True)),
        "has_telegram_token": bool(settings.telegram_bot_token),
        "configured_alert_chats": chats,
        "configured_alert_chats_count": len(chats),
        "raw_autohunter_admin_alert_chats": getattr(settings, "autohunter_admin_alert_chats", None),
        "raw_autohunter_admins": getattr(settings, "autohunter_admins", None),
    }


def send_admin_text_with_report(text: str) -> dict:
    report = {
        "enabled": bool(getattr(settings, "admin_alerts_enabled", True)),
        "has_token": bool(settings.telegram_bot_token),
        "target_chats": list(iter_admin_chat_ids()),
        "attempted": 0,
        "sent": 0,
        "failed": 0,
    }

    if not report["enabled"]:
        logger.info("admin_alerts_skipped_disabled")
        return report

    token = settings.telegram_bot_token
    if not token:
        logger.warning("admin_alerts_skipped_missing_token")
        return report

    if not report["target_chats"]:
        logger.warning(
            "admin_alerts_skipped_no_target_chats",
            extra={
                "autohunter_admin_alert_chats": getattr(settings, "autohunter_admin_alert_chats", None),
                "autohunter_admins": getattr(settings, "autohunter_admins", None),
            },
        )
        return report

    msg = sanitize_for_telegram((text or "").strip())
    if not msg:
        logger.info("admin_alerts_skipped_empty_message")
        return report
    if len(msg) > TELEGRAM_TEXT_MAX:
        msg = msg[: TELEGRAM_TEXT_MAX - 1] + "…"

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    session = get_shared_session("telegram")
    for chat_id in report["target_chats"]:
        report["attempted"] += 1
        try:
            session.post(
                url,
                data={"chat_id": chat_id, "text": msg, "disable_web_page_preview": True},
                timeout=15,
            )
            report["sent"] += 1
        except Exception:
            report["failed"] += 1
            logger.warning("admin_alert_send_failed", extra={"chat_id": chat_id}, exc_info=True)

    logger.info(
        "admin_alert_send_summary",
        extra={
            "attempted": report["attempted"],
            "sent": report["sent"],
            "failed": report["failed"],
        },
    )
    return report


def send_admin_text(text: str) -> None:
    """Envia uma mensagem simples para todos os admins."""
    send_admin_text_with_report(text)
