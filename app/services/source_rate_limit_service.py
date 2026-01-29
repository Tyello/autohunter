from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import select

from app.models.source_config import SourceConfig


def get_source_rate_limit_seconds(source: str, db: Optional[Session] = None) -> int:
    """Return per-source minimum interval between runs in seconds.

    Source-level rate limit is stored in DB (`source_configs.rate_limit_seconds`).

    `db` is optional for backward-compatibility (returns 0 if not provided).
    """
    src = (source or "").lower().strip()
    if not src or db is None:
        return 0

    cfg = db.execute(select(SourceConfig).where(SourceConfig.source == src)).scalar_one_or_none()
    return int(cfg.rate_limit_seconds or 0) if cfg else 0
