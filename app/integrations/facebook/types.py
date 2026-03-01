from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass(slots=True)
class FBValidationResult:
    status: str
    error_kind: Optional[str] = None
    error_message: Optional[str] = None
    checked_at: Optional[datetime] = None


@dataclass(slots=True)
class PairingValidation:
    ok: bool
    reason: Optional[str] = None
