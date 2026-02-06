from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from app.core.settings import settings


@dataclass(frozen=True)
class StorageCookie:
    name: str
    value: str
    domain: str
    path: str
    secure: bool
    httpOnly: bool
    expires: Optional[float]
    sameSite: Optional[str]


_lock = threading.Lock()
_cache: Dict[str, Tuple[float, List[StorageCookie]]] = {}


def _safe(s: str) -> str:
    return (s or "").replace(":", "_").replace("/", "_")


def storage_state_path(*, source: str, proxy_server: Optional[str]) -> str:
    """Compute the same storage_state path used by the Playwright pool.

    Must remain compatible with app.services.playwright_pool._storage_path().
    """
    base = Path(getattr(settings, "playwright_storage_dir", None) or ".data/playwright")
    base.mkdir(parents=True, exist_ok=True)

    proxy_key = proxy_server or "__no_proxy__"
    safe_proxy = _safe(proxy_key)
    safe_source = _safe((source or "unknown").strip().lower() or "unknown")
    return str(base / f"storage_{safe_source}__{safe_proxy}.json")


def _load_storage_cookies(path: str) -> List[StorageCookie]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    cookies = []
    for c in (data.get("cookies") or []):
        try:
            cookies.append(
                StorageCookie(
                    name=str(c.get("name") or ""),
                    value=str(c.get("value") or ""),
                    domain=str(c.get("domain") or ""),
                    path=str(c.get("path") or "/"),
                    secure=bool(c.get("secure")),
                    httpOnly=bool(c.get("httpOnly")),
                    expires=float(c["expires"]) if c.get("expires") is not None else None,
                    sameSite=str(c.get("sameSite")) if c.get("sameSite") is not None else None,
                )
            )
        except Exception:
            continue
    return cookies


def get_cookies_for_ctx(*, source: str, proxy_server: Optional[str]) -> List[StorageCookie]:
    """Load cookies from Playwright storage_state (cached by mtime)."""
    path = storage_state_path(source=source, proxy_server=proxy_server)
    if not os.path.exists(path):
        return []

    try:
        mtime = os.path.getmtime(path)
    except Exception:
        return []

    with _lock:
        hit = _cache.get(path)
        if hit and hit[0] == mtime:
            return hit[1]

        try:
            cookies = _load_storage_cookies(path)
        except Exception:
            cookies = []

        _cache[path] = (mtime, cookies)
        return cookies


def _domain_matches(cookie_domain: str, req_host: str) -> bool:
    d = (cookie_domain or "").lstrip(".").lower()
    h = (req_host or "").lower()
    if not d or not h:
        return False
    return h == d or h.endswith("." + d)


def apply_storage_cookies(session: Any, *, url: str, cookies: List[StorageCookie]) -> int:
    """Apply cookies (loaded from storage_state) to a requests.Session.

    Returns how many cookies were applied.
    """
    try:
        host = urlparse(url).netloc
    except Exception:
        host = ""
    if not host:
        return 0

    applied = 0
    for c in cookies or []:
        if not c.name:
            continue
        if not _domain_matches(c.domain, host):
            continue
        try:
            # requests will handle domain/path scoping
            session.cookies.set(
                name=c.name,
                value=c.value,
                domain=c.domain,
                path=c.path or "/",
            )
            applied += 1
        except Exception:
            continue
    return applied
