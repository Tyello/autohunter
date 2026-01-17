from __future__ import annotations

from typing import Dict, List, Optional

from app.core.settings import settings

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


def _is_enabled(plugin: SourcePlugin) -> bool:
    if plugin.enabled_setting is None:
        return True
    return bool(getattr(settings, plugin.enabled_setting, False))


def list_enabled_sources() -> List[SourcePlugin]:
    return [p for p in list_sources() if _is_enabled(p)]


# Import builtins so they register themselves.
# Important: keep this import at the bottom to avoid circular imports.
from . import builtins  # noqa: E402,F401
