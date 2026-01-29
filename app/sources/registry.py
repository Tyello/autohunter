from __future__ import annotations

from typing import Dict, List, Optional, Set

from sqlalchemy.orm import Session
from sqlalchemy import select

from app.models.source_config import SourceConfig

from .types import SourcePlugin


_REGISTRY: Dict[str, SourcePlugin] = {}


def register_source(plugin: SourcePlugin) -> None:
    name = plugin.name.strip().lower()
    if not name:
        raise ValueError("plugin.name cannot be empty")
    if name in _REGISTRY:
        raise ValueError(f"duplicate source plugin: {name}")
    _REGISTRY[name] = plugin


def get_source(name: str) -> Optional[SourcePlugin]:
    return _REGISTRY.get(name.strip().lower())


def list_sources() -> List[SourcePlugin]:
    return list(_REGISTRY.values())


def list_enabled_sources(db: Optional[Session] = None) -> List[SourcePlugin]:
    """Returns enabled sources.

    - If `db` is provided, DB (`source_configs`) is the source of truth.
    - If `db` is None (e.g. during very early startup), fall back to plugin defaults.
    """
    plugins = list_sources()
    if db is None:
        return [p for p in plugins if bool(getattr(p, "default_enabled", True))]

    try:
        enabled: Set[str] = set(
            s for s in db.execute(select(SourceConfig.source).where(SourceConfig.is_enabled == True)).scalars().all()
        )
        return [p for p in plugins if p.name in enabled]
    except Exception:
        # In case migrations were not applied yet, fall back to defaults.
        return [p for p in plugins if bool(getattr(p, "default_enabled", True))]


# Import builtins so they register themselves.
# Important: keep this import at the bottom to avoid circular imports.
from . import builtins  # noqa: E402,F401
