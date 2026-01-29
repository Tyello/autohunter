from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Any, Dict, Tuple, List

from sqlalchemy.orm import Session
from sqlalchemy import select

from app.core.settings import settings
from app.models.source_config import SourceConfig
from app.sources.registry import list_sources
from app.sources.types import ScrapeContext


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
    return list(
        db.execute(select(SourceConfig).order_by(SourceConfig.source.asc())).scalars().all()
    )


def ensure_source_configs(db: Session) -> int:
    """Garante que existe 1 row em source_configs para cada plugin registrado.

    ⚠️ Nesta fase (patch parcial), fazemos seed a partir dos Settings legado
    (enabled/sched/cooldown/rate_limit/proxy/flags) *somente quando a row ainda não existe*.
    Depois, runtime deve usar o DB como fonte de verdade.

    Retorna quantas rows foram criadas.
    """
    created = 0
    for plugin in list_sources():
        src = plugin.name.strip().lower()
        if not src:
            continue
        if get_source_config(db, src):
            continue

        # Seeds legacy (settings) only once
        is_enabled = True
        if getattr(plugin, "enabled_setting", None):
            is_enabled = bool(getattr(settings, plugin.enabled_setting, True))

        sched_minutes = 60
        if getattr(plugin, "sched_minutes_setting", None):
            sched_minutes = int(getattr(settings, plugin.sched_minutes_setting, 60) or 60)

        cooldown_minutes = 0
        if getattr(plugin, "cooldown_minutes_setting", None):
            cooldown_minutes = int(getattr(settings, plugin.cooldown_minutes_setting, 0) or 0)

        rate_limit_seconds = 0
        if getattr(plugin, "rate_limit_seconds_setting", None):
            rate_limit_seconds = int(getattr(settings, plugin.rate_limit_seconds_setting, 0) or 0)

        # proxy per-source (pattern: source_proxy_<name>)
        proxy_attr = f"source_proxy_{src}"
        proxy_server = getattr(settings, proxy_attr, None)

        # browser flags (special cases)
        browser_fallback_enabled = False
        force_browser = False
        if src == "olx":
            browser_fallback_enabled = bool(getattr(settings, "enable_olx_browser_fallback", False))
            force_browser = bool(getattr(settings, "olx_force_browser", False))

        row = SourceConfig(
            source=src,
            is_enabled=is_enabled,
            sched_minutes=sched_minutes,
            cooldown_minutes=cooldown_minutes,
            rate_limit_seconds=rate_limit_seconds,
            proxy_server=proxy_server,
            browser_fallback_enabled=browser_fallback_enabled,
            force_browser=force_browser,
            extra=None,
        )
        db.add(row)
        created += 1

    return created


def set_source_field(db: Session, source: str, field: str, value: str) -> UpdateResult:
    src = source.strip().lower()
    key = _FIELD_ALIASES.get(field.strip().lower())
    if not key:
        return UpdateResult(False, f"campo inválido: {field}")

    row = get_source_config(db, src)
    if not row:
        return UpdateResult(False, f"source não encontrada: {src}")

    if key in ("is_enabled", "browser_fallback_enabled", "force_browser"):
        b = _coerce_bool(value)
        if b is None:
            return UpdateResult(False, f"valor boolean inválido: {value}")
        setattr(row, key, b)
        return UpdateResult(True)

    if key in ("sched_minutes", "cooldown_minutes", "rate_limit_seconds"):
        i = _coerce_int(value)
        if i is None or i < 0:
            return UpdateResult(False, f"valor int inválido: {value}")
        setattr(row, key, i)
        return UpdateResult(True)

    if key == "proxy_server":
        v = (value or "").strip()
        setattr(row, key, v if v else None)
        return UpdateResult(True)

    return UpdateResult(False, f"campo não suportado: {field}")


def build_scrape_context(db: Session, source: str) -> ScrapeContext:
    """Constrói ScrapeContext usando config do banco.

    Patch parcial: ScrapeContext só carrega proxy. Flags browser ainda serão
    consumidas no patch final.
    """
    src = source.strip().lower()
    cfg = get_source_config(db, src)
    return ScrapeContext(source=src, proxy_server=(cfg.proxy_server if cfg else None))
