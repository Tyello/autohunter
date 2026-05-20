from __future__ import annotations

import logging
from dataclasses import dataclass
from sqlalchemy.orm import Session

from app.models.source_config import SourceConfig
from app.services.source_configs_service import ensure_source_configs, get_source_config, invalidate_source_config_cache
from app.sources.auctions.registry import list_auction_sources, resolve_auction_source_alias, list_supported_auction_source_keys

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AuctionSourceDefaults:
    source_type: str
    enabled: bool
    user_eligible: bool
    admin_only: bool
    status: str


DEFAULTS = {
    "vip_auctions": AuctionSourceDefaults("auction", True, True, False, "production_ready"),
    "mega_auctions": AuctionSourceDefaults("auction", True, False, True, "experimental"),
    "win_auctions": AuctionSourceDefaults("auction", True, False, True, "experimental_functional_vehicle"),
    "sodre_auctions": AuctionSourceDefaults("auction", False, False, True, "blocked/needs_study"),
    "superbid_auctions": AuctionSourceDefaults("auction", True, False, True, "needs_study"),
    "copart_auctions": AuctionSourceDefaults("auction", False, False, True, "needs_study"),
}


def reconcile_auction_source_config_metadata(db: Session) -> int:
    """Reconcile safe auction source metadata with the registry/default map.

    This intentionally updates only metadata fields that do not represent an
    operator decision: ``source_type`` and ``status``. It never changes enabled,
    user_eligible, admin_only, disabled reasons, categories, or any other
    values stored under ``extra``.
    """
    changed = 0
    for source, defaults in DEFAULTS.items():
        cfg = get_source_config(db, source)
        if not cfg:
            continue
        if getattr(cfg, "source_type", None) != defaults.source_type:
            cfg.source_type = defaults.source_type
            changed += 1
        if (getattr(cfg, "status", None) or "") != defaults.status:
            cfg.status = defaults.status
            changed += 1
    if changed:
        invalidate_source_config_cache()
        db.flush()
    return changed


def ensure_auction_source_configs(db: Session) -> int:
    ensure_source_configs(db)
    changed = 0
    for item in list_auction_sources():
        cfg = get_source_config(db, item.key)
        if not cfg:
            cfg = SourceConfig(source=item.key)
            db.add(cfg)
            new_row = True
        else:
            new_row = False
        d = DEFAULTS[item.key]
        if new_row:
            cfg.is_enabled = d.enabled
            cfg.user_eligible = d.user_eligible
            cfg.admin_only = d.admin_only
            cfg.status = d.status
            cfg.source_type = d.source_type
            changed += 1
            continue
        if getattr(cfg, "admin_only", None) is None:
            cfg.admin_only = d.admin_only
            changed += 1
        if getattr(cfg, "user_eligible", None) is None:
            cfg.user_eligible = d.user_eligible
            changed += 1
    if changed:
        invalidate_source_config_cache()
        db.flush()
    changed += reconcile_auction_source_config_metadata(db)
    return changed


def _resolve_key(source_key: str) -> str | None:
    return resolve_auction_source_alias(source_key) or (source_key if source_key in list_supported_auction_source_keys() else None)


def is_auction_source_enabled(db: Session, source_key: str) -> bool:
    key = _resolve_key(source_key)
    if not key:
        return False
    cfg = get_source_config(db, key)
    if not cfg:
        logger.warning("auction source without config, allowing admin runtime path only: %s", key)
        return True
    return bool(getattr(cfg, "is_enabled", False))


def is_auction_source_user_eligible(db: Session, source_key: str) -> bool:
    key = _resolve_key(source_key)
    if not key:
        return False
    cfg = get_source_config(db, key)
    if not cfg:
        return False
    return bool(getattr(cfg, "is_enabled", False) and getattr(cfg, "user_eligible", False))


def list_enabled_auction_sources(db: Session) -> set[str]:
    ensure_auction_source_configs(db)
    return {item.key for item in list_auction_sources() if is_auction_source_enabled(db, item.key)}


def list_user_eligible_auction_sources(db: Session) -> set[str]:
    ensure_auction_source_configs(db)
    return {item.key for item in list_auction_sources() if is_auction_source_user_eligible(db, item.key)}
