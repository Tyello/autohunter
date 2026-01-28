from __future__ import annotations

from app.core.settings import settings


def get_source_rate_limit_seconds(source: str) -> int:
    """Return per-source minimum interval between runs in seconds.

    Use this to avoid hammering sites like OLX. 0 disables throttling.
    """
    src = (source or "").lower().strip()

    if src == "olx":
        return int(settings.rate_limit_olx_seconds or 0)
    if src == "webmotors":
        return int(settings.rate_limit_webmotors_seconds or 0)
    if src == "gogarage":
        return int(settings.rate_limit_gogarage_seconds or 0)
    if src == "chavesnamao":
        return int(settings.rate_limit_chavesnamao_seconds or 0)
    if src == "mercadolivre":
        return int(settings.rate_limit_mercadolivre_seconds or 0)

    if src == "kavak":
        return int(getattr(settings, "rate_limit_kavak_seconds", 0) or 0)
    if src == "mobiauto":
        return int(getattr(settings, "rate_limit_mobiauto_seconds", 0) or 0)
    if src == "icarros":
        return int(getattr(settings, "rate_limit_icarros_seconds", 0) or 0)
    if src == "facebook_marketplace":
        return int(getattr(settings, "rate_limit_facebook_marketplace_seconds", 0) or 0)

    return 0
