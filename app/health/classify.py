from __future__ import annotations

from typing import Any

from app.health.models import RunStatus


def _to_int(v: Any) -> int | None:
    try:
        if v is None:
            return None
        return int(v)
    except Exception:
        return None


def classify_error(exc: Exception) -> tuple[str, RunStatus, bool | None, int | None, str]:
    msg = f"{type(exc).__name__}: {exc}"
    low = msg.lower()

    status_code = _to_int(getattr(exc, "status_code", None) or getattr(getattr(exc, "response", None), "status_code", None))

    if status_code == 403:
        return ("http_403", RunStatus.BLOCKED, True, 403, "blocked_403")
    if status_code == 429:
        return ("http_429", RunStatus.BLOCKED, True, 429, "blocked_429")

    if "captcha" in low or "cloudflare" in low or "cf challenge" in low:
        return ("blocked_captcha", RunStatus.BLOCKED, True, status_code, "blocked_captcha")

    if "proxy" in low or "socks" in low:
        return ("proxy_error", RunStatus.PROXY, True, status_code, "proxy_error")

    if "timeout" in low:
        return ("timeout", RunStatus.NET, True, status_code, "timeout")

    if "dns" in low or "name or service not known" in low or "connection" in low or "connect" in low:
        return ("connection_error", RunStatus.NET, True, status_code, "http_error")

    if "selector" in low or "parse" in low or "jsondecode" in low or "valueerror" in low:
        return ("parse_error", RunStatus.PARSE, False, status_code, "parse_error")

    if "missing field" in low or "invalid data" in low or "missing required" in low:
        return ("invalid_data", RunStatus.DATA, False, status_code, "missing_fields_other")

    return ("unknown_error", RunStatus.ERR, None, status_code, "unknown_error")
