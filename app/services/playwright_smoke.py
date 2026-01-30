from __future__ import annotations

from typing import Any, Dict

from app.core.settings import settings


def assert_playwright_ready() -> Dict[str, Any]:
    """
    Smoke test leve:
    - Se in-process: pool.stats() força start do worker e valida import/boot.
    - Se remoto: chama stats() (e opcionalmente health()).
    """
    if not bool(getattr(settings, "enable_playwright", False)):
        return {"ok": True, "skipped": True, "backend": "disabled"}

    if getattr(settings, "playwright_endpoint", None):
        from app.services.playwright_client import get_playwright_client
        client = get_playwright_client()
        # health pode ser opcional; stats já valida endpoint e auth.
        st = client.stats()
        return {"ok": True, "backend": "remote", "stats": st}

    from app.services.playwright_pool import get_playwright_pool
    st = get_playwright_pool().stats()
    return {"ok": True, "backend": "inprocess", "stats": st}
