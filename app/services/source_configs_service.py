from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Any, Dict, List

from sqlalchemy.orm import Session
from sqlalchemy import select

from app.models.source_config import SourceConfig
from app.sources.registry import list_sources, get_source
from app.sources.types import ScrapeContext


def _normalize_proxy_server(v: Any) -> Optional[str]:
    """Normalize proxy strings coming from DB/user input.

    Guarantees that "no proxy" values don't leak into scrapers (e.g. "NULL").
    Also auto-prefixes scheme for common inputs like "host:port".
    """
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    if s.lower() in {"null", "none", "nil"}:
        return None
    # requests/playwright proxy expects a scheme; accept explicit schemes as-is.
    if "://" not in s:
        s = "http://" + s
    return s


@dataclass
class UpdateResult:
    ok: bool
    error: Optional[str] = None


_FIELD_ALIASES = {
    "enabled": "is_enabled",
    "enable": "is_enabled",
    "is_enabled": "is_enabled",
    "sched": "sched_minutes",
    "schedule": "sched_minutes",
    "sched_minutes": "sched_minutes",
    "cool": "cooldown_minutes",
    "cooldown": "cooldown_minutes",
    "cooldown_minutes": "cooldown_minutes",
    "rate": "rate_limit_seconds",
    "ratelimit": "rate_limit_seconds",
    "rate_limit_seconds": "rate_limit_seconds",
    "proxy": "proxy_server",
    "proxy_server": "proxy_server",
    "fallback": "browser_fallback_enabled",
    "browser_fallback_enabled": "browser_fallback_enabled",
    "force": "force_browser",
    "force_browser": "force_browser",
}


def _coerce_bool(value: str) -> Optional[bool]:
    v = (value or "").strip().lower()
    if v in ("true", "1", "yes", "y", "on", "enable", "enabled"):
        return True
    if v in ("false", "0", "no", "n", "off", "disable", "disabled"):
        return False
    return None


def _coerce_int(value: str) -> Optional[int]:
    try:
        return int(str(value).strip())
    except Exception:
        return None


def get_source_config(db: Session, source: str) -> Optional[SourceConfig]:
    return db.execute(
        select(SourceConfig).where(SourceConfig.source == source.strip().lower())
    ).scalar_one_or_none()


def list_source_configs(db: Session) -> List[SourceConfig]:
    return list(db.execute(select(SourceConfig).order_by(SourceConfig.source.asc())).scalars().all())


def ensure_source_configs(db: Session) -> int:
    """Ensure 1 row in `source_configs` for every registered plugin.

    DB is the source of truth. `default_*` fields in plugins are used only as seed
    when a row does not exist yet.

    Returns number of rows created (not committed).
    """
    existing_sources = set(
        db.execute(select(SourceConfig.source)).scalars().all()
    )
    created = 0
    updated = 0
    for plugin in list_sources():
        src = plugin.name.strip().lower()
        if not src:
            continue
        if src in existing_sources:
            # Backfill missing keys in `extra` using plugin defaults (DB remains source of truth).
            # This is intentionally non-destructive: it only fills keys that are absent.
            try:
                defaults = getattr(plugin, "default_extra", None) or {}
                if defaults:
                    cfg = get_source_config(db, src)
                    if cfg is not None:
                        cur = cfg.extra or {}
                        changed = False
                        for k, v in defaults.items():
                            if k not in cur:
                                cur[k] = v
                                changed = True
                        if changed:
                            cfg.extra = cur
                            updated += 1
            except Exception:
                pass
            continue

        row = SourceConfig(
            source=src,
            is_enabled=bool(getattr(plugin, "default_enabled", True)),
            sched_minutes=int(getattr(plugin, "default_sched_minutes", 60) or 60),
            cooldown_minutes=int(getattr(plugin, "default_cooldown_minutes", 0) or 0),
            rate_limit_seconds=int(getattr(plugin, "default_rate_limit_seconds", 0) or 0),
            proxy_server=getattr(plugin, "default_proxy_server", None),
            browser_fallback_enabled=bool(getattr(plugin, "default_browser_fallback_enabled", False)),
            force_browser=bool(getattr(plugin, "default_force_browser", False)),
            extra=getattr(plugin, "default_extra", None),
        )
        db.add(row)
        created += 1

    # SessionLocal in this project uses autoflush=False. We must flush here so
    # that subsequent SELECTs in the same transaction can "see" freshly added
    # rows (e.g. /admin sources enable <source>). Commit is handled by callers.
    if created or updated:
        try:
            db.flush()
        except Exception:
            # If migrations haven't run yet, flush may fail; callers will handle.
            pass

    return created


def set_source_field(db: Session, source: str, field: str, value: str) -> SourceConfig:
    """Set a single field for a source config row and return the updated row (not committed).

    This function is used by /admin sources <field> ... commands.
    It raises ValueError for invalid input so handlers can show a clean message.
    """
    src = (source or "").strip().lower()
    key = _FIELD_ALIASES.get((field or "").strip().lower())
    if not key:
        raise ValueError(f"campo inválido: {field}")

    row = get_source_config(db, src)
    if not row:
        # If the DB is missing the row (new plugin, fresh DB), seed + retry.
        ensure_source_configs(db)
        row = get_source_config(db, src)
    if not row:
        raise ValueError(f"source não encontrada: {src}")

    if key in ("is_enabled", "browser_fallback_enabled", "force_browser"):
        b = _coerce_bool(value)
        if b is None:
            raise ValueError(f"valor boolean inválido: {value}")
        setattr(row, key, b)
        return row

    if key in ("sched_minutes", "cooldown_minutes", "rate_limit_seconds"):
        i = _coerce_int(value)
        if i is None or i < 0:
            raise ValueError(f"valor int inválido: {value}")
        setattr(row, key, i)
        return row

    if key == "proxy_server":
        v = (value or "").strip()
        setattr(row, key, v if v else None)
        return row

    raise ValueError(f"campo não suportado: {field}")
def reset_source_config(db: Session, source: str) -> SourceConfig:
    """Reset a single source config to plugin defaults (DB is source of truth).

    If the row does not exist yet, it is created (not committed).
    Raises ValueError if source/plugin is unknown.
    """
    src = source.strip().lower()
    plugin = get_source(src)
    if not plugin:
        raise ValueError(f"source não encontrada: {src}")

    cfg = get_source_config(db, src)
    if not cfg:
        cfg = SourceConfig(source=src)
        db.add(cfg)

    cfg.is_enabled = bool(getattr(plugin, "default_enabled", True))
    cfg.sched_minutes = int(getattr(plugin, "default_sched_minutes", 60) or 60)
    cfg.cooldown_minutes = int(getattr(plugin, "default_cooldown_minutes", 0) or 0)
    cfg.rate_limit_seconds = int(getattr(plugin, "default_rate_limit_seconds", 0) or 0)
    cfg.proxy_server = getattr(plugin, "default_proxy_server", None)
    cfg.browser_fallback_enabled = bool(getattr(plugin, "default_browser_fallback_enabled", False))
    cfg.force_browser = bool(getattr(plugin, "default_force_browser", False))
    cfg.extra = getattr(plugin, "default_extra", None)
    return cfg



def build_scrape_context(db: Session, source: str) -> ScrapeContext:
    """Build ScrapeContext using DB config (source_configs)."""
    src = source.strip().lower()
    cfg = get_source_config(db, src)
    if not cfg:
        ensure_source_configs(db)
        cfg = get_source_config(db, src)

    # If still missing, fallback to plugin defaults
    if not cfg:
        plugin = get_source(src)
        extra = getattr(plugin, "default_extra", None) if plugin else None
        extra = extra or {}

        def _get_int(key: str):
            v = extra.get(key)
            if v is None:
                return None
            try:
                return int(v)
            except Exception:
                return None

        def _get_float(key: str):
            v = extra.get(key)
            if v is None:
                return None
            try:
                return float(v)
            except Exception:
                return None

        def _get_str(key: str):
            v = extra.get(key)
            if v is None:
                return None
            s = str(v).strip()
            return s or None

        return ScrapeContext(
            source=src,
            proxy_server=_normalize_proxy_server(getattr(plugin, "default_proxy_server", None) if plugin else None),
            browser_fallback_enabled=bool(getattr(plugin, "default_browser_fallback_enabled", False)) if plugin else False,
            force_browser=bool(getattr(plugin, "default_force_browser", False)) if plugin else False,
            http_connect_timeout_s=_get_float("http_connect_timeout_s"),
            http_read_timeout_s=_get_float("http_read_timeout_s"),
            http_timeout_s=_get_float("http_timeout_s"),
            http_min_delay_ms=_get_int("http_min_delay_ms"),
            http_max_delay_ms=_get_int("http_max_delay_ms"),
            browser_timeout_ms=_get_int("browser_timeout_ms"),
            browser_wait_until=_get_str("browser_wait_until"),
            browser_min_delay_ms=_get_int("browser_min_delay_ms"),
            browser_max_delay_ms=_get_int("browser_max_delay_ms"),
            extra=extra if extra else None,
        )

    extra = cfg.extra or {}

    def _get_int(key: str) -> int | None:
        v = extra.get(key)
        if v is None:
            return None
        try:
            return int(v)
        except Exception:
            return None

    def _get_float(key: str) -> float | None:
        v = extra.get(key)
        if v is None:
            return None
        try:
            return float(v)
        except Exception:
            return None

    def _get_str(key: str) -> str | None:
        v = extra.get(key)
        if v is None:
            return None
        s = str(v).strip()
        return s or None

    return ScrapeContext(
        source=src,
        proxy_server=_normalize_proxy_server(cfg.proxy_server),
        browser_fallback_enabled=bool(cfg.browser_fallback_enabled),
        force_browser=bool(cfg.force_browser),
        http_connect_timeout_s=_get_float("http_connect_timeout_s"),
        http_read_timeout_s=_get_float("http_read_timeout_s"),
        http_timeout_s=_get_float("http_timeout_s"),
        http_min_delay_ms=_get_int("http_min_delay_ms"),
        http_max_delay_ms=_get_int("http_max_delay_ms"),
        browser_timeout_ms=_get_int("browser_timeout_ms"),
        browser_wait_until=_get_str("browser_wait_until"),
        browser_min_delay_ms=_get_int("browser_min_delay_ms"),
        browser_max_delay_ms=_get_int("browser_max_delay_ms"),
        extra=extra if extra else None,
    )
