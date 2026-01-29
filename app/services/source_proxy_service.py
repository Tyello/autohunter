from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.models.source_config import SourceConfig
from sqlalchemy import select


def get_source_proxy_server(source: str, db: Optional[Session] = None) -> Optional[str]:
    """Return proxy server URL for a given source.

    Source-level proxy is stored in DB (`source_configs.proxy_server`).

    `db` is optional for backward-compatibility (returns None if not provided).
    """
    src = (source or "").lower().strip()
    if not src:
        return None
    if db is None:
        return None

    cfg = db.execute(select(SourceConfig).where(SourceConfig.source == src)).scalar_one_or_none()
    return cfg.proxy_server if cfg else None
