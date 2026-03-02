from __future__ import annotations

import asyncio
import re
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from app.integrations.facebook.constants import (
    STATUS_ACTIVE,
    STATUS_BLOCKED,
    STATUS_CHALLENGE_REQUIRED,
    STATUS_DISABLED,
    STATUS_EXPIRED,
    STATUS_PENDING_AUTH,
)

PAIRING_CODE_RE = re.compile(r"^FB-[A-Z0-9]{4}$")

_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    STATUS_PENDING_AUTH: {STATUS_ACTIVE, STATUS_CHALLENGE_REQUIRED, STATUS_EXPIRED, STATUS_BLOCKED},
    STATUS_ACTIVE: {STATUS_ACTIVE, STATUS_CHALLENGE_REQUIRED, STATUS_EXPIRED, STATUS_BLOCKED, STATUS_DISABLED},
    STATUS_DISABLED: set(),
    STATUS_CHALLENGE_REQUIRED: {STATUS_ACTIVE, STATUS_CHALLENGE_REQUIRED, STATUS_EXPIRED, STATUS_BLOCKED, STATUS_DISABLED},
    STATUS_EXPIRED: {STATUS_ACTIVE, STATUS_CHALLENGE_REQUIRED, STATUS_EXPIRED, STATUS_BLOCKED, STATUS_DISABLED},
    STATUS_BLOCKED: {STATUS_ACTIVE, STATUS_CHALLENGE_REQUIRED, STATUS_EXPIRED, STATUS_BLOCKED, STATUS_DISABLED},
}


class UserOperationBusyError(RuntimeError):
    pass


class UserLockRegistry:
    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._guard = asyncio.Lock()

    async def acquire(self, user_id: str) -> asyncio.Lock | None:
        async with self._guard:
            lock = self._locks[user_id]
            if lock.locked():
                return None
            await lock.acquire()
            return lock


_user_locks = UserLockRegistry()


@asynccontextmanager
async def fb_user_operation_lock(user_id: str):
    lock = await _user_locks.acquire(user_id)
    if lock is None:
        raise UserOperationBusyError("busy_try_again")
    try:
        yield
    finally:
        lock.release()


def normalize_pairing_code(code: str) -> str:
    return (code or "").strip().upper()


def validate_pairing_code_format(code: str) -> bool:
    return bool(PAIRING_CODE_RE.match(code))


def can_transition_status(current: str, target: str) -> bool:
    if target == STATUS_PENDING_AUTH:
        return False
    return target in _ALLOWED_TRANSITIONS.get(current, set())


def normalize_transition_status(current: str, target: str) -> str:
    if can_transition_status(current, target):
        return target
    return current


def is_expired(expires_at: datetime | None, now: datetime | None = None) -> bool:
    if not expires_at:
        return True
    now = now or datetime.now(timezone.utc)
    exp = expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=timezone.utc)
    return exp < now


def action_hint_for_status(status: str) -> str:
    if status == STATUS_ACTIVE:
        return "OK"
    if status == STATUS_PENDING_AUTH:
        return "Finalize no link"
    if status in {STATUS_EXPIRED, STATUS_CHALLENGE_REQUIRED, STATUS_BLOCKED}:
        return "Reautenticar via /fb connect"
    if status == STATUS_DISABLED:
        return "Sessão desabilitada; use /fb connect"
    return "Reautenticar via /fb connect"
