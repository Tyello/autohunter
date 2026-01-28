from __future__ import annotations

from typing import Iterable, List
import requests

from app.core.settings import settings
from app.bot.text_sanitize import sanitize_for_telegram


TELEGRAM_TEXT_MAX = 4096


def _parse_admins(raw: str | None) -> List[int]:
    raw = raw or ""
    out: List[int] = []
    for part in raw.split(","):
        part = (part or "").strip()
        if part.isdigit():
            out.append(int(part))
    return out


def iter_admin_chat_ids() -> Iterable[int]:
    return _parse_admins(settings.autohunter_admins)


def send_admin_text(text: str) -> None:
    """Envia uma mensagem simples para todos os admins."""
    if not getattr(settings, "admin_alerts_enabled", True):
        return

    token = settings.telegram_bot_token
    if not token:
        return

    msg = sanitize_for_telegram((text or "").strip())
    if not msg:
        return
    if len(msg) > TELEGRAM_TEXT_MAX:
        msg = msg[: TELEGRAM_TEXT_MAX - 1] + "…"

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for chat_id in iter_admin_chat_ids():
        try:
            requests.post(
                url,
                data={"chat_id": chat_id, "text": msg, "disable_web_page_preview": True},
                timeout=15,
            )
        except Exception:
            continue
