from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from app.sources.types import SourcePlugin


@dataclass(frozen=True, slots=True)
class SourceOperationalClassification:
    role: str
    include_in_critical_stale: bool
    reason: str


def _is_enabled(cfg: Any, plugin: SourcePlugin) -> bool:
    if cfg is None:
        return bool(getattr(plugin, "default_enabled", True))
    return bool(getattr(cfg, "is_enabled", False))


def _manual_role_override(plugin: SourcePlugin) -> Optional[str]:
    extra = getattr(plugin, "default_extra", None)
    if not isinstance(extra, dict):
        return None
    role = extra.get("operational_role")
    if isinstance(role, str) and role.strip():
        return role.strip().lower()
    return None


def classify_source_operational_role(
    plugin: SourcePlugin,
    cfg: Any = None,
    state: Any = None,
) -> SourceOperationalClassification:
    del state  # reserved for future policy extensions

    enabled = _is_enabled(cfg, plugin)
    if not enabled:
        return SourceOperationalClassification("disabled", False, "disabled")

    supports_wishlist = bool(getattr(plugin, "supports_wishlist_monitoring", True))
    implemented = callable(getattr(plugin, "scrape", None))

    if not supports_wishlist:
        return SourceOperationalClassification("auxiliary", False, "auxiliary/feed")
    if not implemented:
        return SourceOperationalClassification("not_implemented", False, "scrape=None")

    explicit_role = _manual_role_override(plugin)
    if explicit_role in {"experimental", "deprioritized", "fragile"}:
        return SourceOperationalClassification(explicit_role, True, f"explicit:{explicit_role}")

    return SourceOperationalClassification("primary", True, "wishlist+implemented+enabled")


def should_include_in_critical_stale(plugin: SourcePlugin, cfg: Any = None) -> bool:
    return classify_source_operational_role(plugin, cfg=cfg).include_in_critical_stale


def source_operational_hint(plugin: SourcePlugin, state: Any = None) -> Optional[str]:
    source_name = str(getattr(plugin, "name", "")).strip().lower()
    if source_name != "webmotors" or state is None:
        return None

    last_status = str(getattr(state, "last_status", "") or "").lower()
    next_allowed_at = getattr(state, "next_allowed_at", None)
    if last_status == "blocked" or next_allowed_at is not None:
        return "source frágil/anti-bot recorrente"
    return None
