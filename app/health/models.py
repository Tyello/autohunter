from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class RunStatus(str, Enum):
    OK = "OK"
    ERR = "ERR"
    BLOCKED = "BLOCKED"
    NET = "NET"
    PROXY = "PROXY"
    DATA = "DATA"
    PARSE = "PARSE"


class LastError(BaseModel):
    category: str
    message: str
    http_status: Optional[int] = None
    retryable: Optional[bool] = None


class RunSummary(BaseModel):
    source_name: str
    started_at: datetime
    ended_at: datetime
    dur_ms: int
    status: RunStatus

    found: int = 0
    inserted: int = 0
    matched: int = 0
    queued: int = 0
    already_notified: int = 0
    filtered_out: int = 0
    skipped: int = 0
    blocked: int = 0
    errors: int = 0

    reason_buckets: dict[str, int] = Field(default_factory=dict)
    last_error: Optional[LastError] = None
    notes: list[str] = Field(default_factory=list)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
