from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, Optional

from app.core.runtime_paths import playwright_storage_dir


def _safe(s: str) -> str:
    return s.replace(":", "_").replace("/", "_")


def storage_state_path(*, source: str, proxy_server: Optional[str]) -> Path:
    base = playwright_storage_dir()
    base.mkdir(parents=True, exist_ok=True)
    proxy_key = proxy_server or "__no_proxy__"
    return base / f"storage_{_safe(source)}__{_safe(proxy_key)}.json"


def load_cookies_from_storage_state(*, source: str, proxy_server: Optional[str]) -> Dict[str, str]:
    """Extract cookies from a Playwright storage_state file.

    Format:
    {
      "cookies": [{"name": "...", "value": "...", ...}, ...],
      "origins": [...]
    }
    """
    path = storage_state_path(source=source, proxy_server=proxy_server)
    if not path.exists():
        return {}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    cookies = {}
    for c in data.get("cookies") or []:
        name = c.get("name")
        value = c.get("value")
        if name and value:
            cookies[str(name)] = str(value)
    return cookies
