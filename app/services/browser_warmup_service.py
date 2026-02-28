from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from app.scrapers.diagnostics import current_diagnostics
from app.services.browser_fetcher import _get_backend

@dataclass
class WarmupResult:
    ok: bool
    storage_path: str
    steps: int
    error: str = ""

def warmup_source(
    *,
    source: str,
    backend=None,
    proxy: Optional[str] = None,
    proxy_server: Optional[str] = None,
    steps: int = 2,
    timeout_ms: int = 120_000,
) -> WarmupResult:
    """
    Warm a browser session (cookies/localStorage) and persist storage_state per source+proxy.

    This function is designed to work with the project's Playwright pool backend.
    If the backend doesn't implement warmup(), it will raise an AttributeError.
    """
    diag = current_diagnostics()
    if diag is not None:
        diag.note("warmup_source", source)
        diag.note("warmup_steps", steps)

    proxy_use = proxy_server or proxy
    src = (source or "").strip().lower()
    # Default entry points per source
    home = "https://www.webmotors.com.br/" if src == "webmotors" else None

    try:
        if backend is None:
            backend = _get_backend()
        if hasattr(backend, "warmup"):
            res = backend.warmup(
                home,
                source=src,
                proxy_server=proxy_use,
                timeout_ms=timeout_ms,
            )
            storage_path = ""
            if isinstance(res, dict):
                storage_path = str(res.get("storage_path") or "")
            return WarmupResult(ok=True, storage_path=storage_path, steps=steps)
        raise AttributeError("backend.warmup not implemented")
    except Exception as e:
        if diag is not None:
            diag.flag("warmup_ok", False)
            diag.note("warmup_error", str(e)[:300])
        return WarmupResult(ok=False, storage_path="", steps=steps, error=str(e))
