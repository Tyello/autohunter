from __future__ import annotations

import time
import traceback
from typing import Optional, Dict, Any

from app.core.settings import settings
from app.services.admin_alerts_service import send_admin_text

_LAST_SENT: Dict[str, float] = {}

_BUG_TYPES = {
    "AttributeError",
    "ImportError",
    "ModuleNotFoundError",
    "SyntaxError",
    "NameError",
    "TypeError",
    "PlaywrightInitError",
}


def maybe_alert_programming_error(
    component: str,
    exc: BaseException,
    *,
    url: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    if not bool(getattr(settings, "admin_programming_errors_enabled", True)):
        return

    exc_type = type(exc).__name__
    if exc_type not in _BUG_TYPES:
        return

    throttle_s = int(getattr(settings, "admin_programming_errors_throttle_seconds", 600) or 600)

    key = f"{exc_type}|{component}|{str(exc)[:120]}|{url or '-'}"
    now = time.time()
    last = _LAST_SENT.get(key)
    if last and (now - last) < throttle_s:
        return
    _LAST_SENT[key] = now

    tb = traceback.format_exc(limit=8)
    msg = (
        "🧨 AutoHunter — erro de programação\n"
        f"component: {component}\n"
        f"type: {exc_type}\n"
        f"url: {url or '-'}\n"
        f"err: {str(exc)[:600]}\n"
        f"tb: {tb[-1200:]}"
    )
    # send_admin_text já manda SOMENTE pros chats de admin (conforme sua exigência)
    send_admin_text(msg)
