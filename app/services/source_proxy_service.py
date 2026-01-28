from __future__ import annotations

from typing import Optional

from app.core.settings import settings


def get_source_proxy_server(source: str) -> Optional[str]:
    """Return proxy server URL for a given source, if configured in Settings.

    Env vars (loaded via Settings):
      SOURCE_PROXY_OLX
      SOURCE_PROXY_WEBMOTORS
      SOURCE_PROXY_GOGARAGE

    If not set, returns None and the system runs without proxy.
    """

    src = (source or "").lower().strip()
    if src == "olx":
        return settings.source_proxy_olx
    if src == "webmotors":
        return settings.source_proxy_webmotors
    if src == "gogarage":
        return settings.source_proxy_gogarage
    return None