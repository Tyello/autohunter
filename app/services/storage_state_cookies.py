from __future__ import annotations

from pathlib import Path
from typing import Optional

from app.core.runtime_paths import playwright_storage_dir


def _safe(s: str) -> str:
    return s.replace(":", "_").replace("/", "_")


def storage_state_path(*, source: str, proxy_server: Optional[str]) -> Path:
    base = playwright_storage_dir()
    base.mkdir(parents=True, exist_ok=True)
    proxy_key = proxy_server or "__no_proxy__"
    return base / f"storage_{_safe(source)}__{_safe(proxy_key)}.json"
