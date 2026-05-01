from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

_TOKEN_TTL_SECONDS = 900
_STORE: dict[str, dict[str, str | int]] = {}


def _now_ts() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def issue_tracking_callback_token(*, user_id: str, wishlist_id: str, listing_id: str, ttl_seconds: int = _TOKEN_TTL_SECONDS) -> str:
    now = _now_ts()
    exp = now + max(1, int(ttl_seconds))
    seed = f"{user_id}:{wishlist_id}:{listing_id}:{now}:{secrets.token_urlsafe(8)}".encode("utf-8")
    token = hashlib.sha256(seed).hexdigest()[:20]
    _STORE[token] = {"u": str(user_id), "w": str(wishlist_id), "l": str(listing_id), "iat": now, "exp": exp}
    return token


def resolve_tracking_callback_token(token: str) -> tuple[dict[str, str | int] | None, str | None]:
    payload = _STORE.get(token)
    if not payload:
        return None, "invalid"
    if int(payload.get("exp") or 0) <= _now_ts():
        _STORE.pop(token, None)
        return None, "expired"
    return payload, None
