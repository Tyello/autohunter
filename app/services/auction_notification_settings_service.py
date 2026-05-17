from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.core.settings import settings
from app.services.app_kv_service import get_kv, set_kv

AUCTION_NOTIFICATION_SETTINGS_KEY = "auction_notification_settings"

_FIELD_DEFAULTS: dict[str, Any] = {
    "enabled": False,
    "dry_run": True,
    "scheduler_minutes": 60,
    "max_wishlists_per_run": 20,
    "max_per_wishlist": 1,
    "max_per_user_per_day": 3,
    "min_score": 60,
    "max_lot_age_hours": 48,
}
_FIELD_RANGES: dict[str, tuple[int, int]] = {
    "scheduler_minutes": (15, 1440),
    "max_wishlists_per_run": (1, 200),
    "max_per_wishlist": (1, 3),
    "max_per_user_per_day": (1, 10),
    "min_score": (0, 100),
    "max_lot_age_hours": (0, 720),
}
_ENV_MAP = {
    "enabled": "auction_notifications_enabled",
    "dry_run": "auction_notifications_dry_run",
    "scheduler_minutes": "auction_notifications_scheduler_minutes",
    "max_wishlists_per_run": "auction_notifications_max_wishlists_per_run",
    "max_per_wishlist": "auction_notifications_max_per_wishlist",
    "max_per_user_per_day": "auction_notifications_max_per_user_per_day",
    "min_score": "auction_notifications_min_score_safe",
    "max_lot_age_hours": "auction_notifications_max_lot_age_hours_safe",
}


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        v = value.strip().lower()
        if v in {"1", "true", "yes", "sim", "on"}:
            return True
        if v in {"0", "false", "no", "nao", "não", "off"}:
            return False
    return bool(value)


def _normalize_value(key: str, value: Any) -> Any:
    if key in {"enabled", "dry_run"}:
        return _to_bool(value)
    ivalue = int(value)
    low, high = _FIELD_RANGES[key]
    return max(low, min(high, ivalue))


def _raw_runtime(db: Session) -> dict[str, Any]:
    data = get_kv(db, AUCTION_NOTIFICATION_SETTINGS_KEY)
    return data if isinstance(data, dict) else {}


def get_auction_notification_runtime_settings(db: Session) -> dict[str, Any]:
    runtime = _raw_runtime(db)
    out: dict[str, Any] = {"source": {}}
    for key, env_attr in _ENV_MAP.items():
        if key in runtime and runtime.get(key) is not None:
            out[key] = _normalize_value(key, runtime.get(key))
            out["source"][key] = "runtime"
        else:
            env_value = getattr(settings, env_attr, _FIELD_DEFAULTS[key])
            out[key] = _normalize_value(key, env_value)
            out["source"][key] = "env"

    kill_switch = bool(getattr(settings, "auction_notifications_kill_switch", False))
    out["kill_switch"] = kill_switch
    out["enabled_raw"] = bool(out["enabled"])
    if kill_switch:
        out["enabled"] = False
    return out


def set_runtime_setting(db: Session, key: str, value: Any, updated_by: str | None = None) -> None:
    runtime = _raw_runtime(db)
    runtime[key] = _normalize_value(key, value)
    runtime["updated_at"] = datetime.now(timezone.utc).isoformat()
    runtime["updated_by"] = str(updated_by or "-")
    set_kv(db, AUCTION_NOTIFICATION_SETTINGS_KEY, runtime)


def reset_runtime_setting(db: Session, key: str, updated_by: str | None = None) -> None:
    runtime = _raw_runtime(db)
    if key in runtime:
        runtime.pop(key, None)
        runtime["updated_at"] = datetime.now(timezone.utc).isoformat()
        runtime["updated_by"] = str(updated_by or "-")
        set_kv(db, AUCTION_NOTIFICATION_SETTINGS_KEY, runtime)


def reset_all_runtime_settings(db: Session) -> None:
    set_kv(db, AUCTION_NOTIFICATION_SETTINGS_KEY, {})
