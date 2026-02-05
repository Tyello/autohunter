from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Optional

import requests
from requests.cookies import create_cookie

from app.services.storage_state_cookies import storage_state_path

_cache_lock = threading.Lock()
_cookies_cache: dict[str, tuple[float, list[dict]]] = {}


def _load_storage_state_cookies(*, source: str, proxy_server: Optional[str]) -> list[dict]:
    path = storage_state_path(source=source, proxy_server=proxy_server)
    p = Path(path)
    if not p.exists():
        return []

    cache_key = str(p)
    try:
        mtime = p.stat().st_mtime
    except Exception:
        return []

    with _cache_lock:
        hit = _cookies_cache.get(cache_key)
        if hit and hit[0] == mtime:
            return hit[1]

    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        cookies = data.get("cookies") or []
        if not isinstance(cookies, list):
            cookies = []
    except Exception:
        cookies = []

    with _cache_lock:
        _cookies_cache[cache_key] = (mtime, cookies)
    return cookies


def inject_storage_state_cookies(
    sess: requests.Session,
    *,
    source: Optional[str],
    proxy_server: Optional[str],
) -> int:
    """Inject Playwright storage_state cookies into a requests Session.

    Returns the number of cookies injected.
    """
    src = (source or "").strip().lower()
    if not src:
        return 0

    injected = 0
    for c in _load_storage_state_cookies(source=src, proxy_server=proxy_server):
        if not isinstance(c, dict):
            continue
        name = c.get("name")
        value = c.get("value")
        if not name or value is None:
            continue
        try:
            cookie = create_cookie(
                name=str(name),
                value=str(value),
                domain=(c.get("domain") or ""),
                path=(c.get("path") or "/"),
                secure=bool(c.get("secure")),
            )
            sess.cookies.set_cookie(cookie)
            injected += 1
        except Exception:
            continue

    return injected

