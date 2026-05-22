from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from app.sources.types import SourcePlugin

ALLOWED_OPERATIONAL_ROLES = {
    "primary",
    "auxiliary",
    "experimental",
    "fragile",
    "deprioritized",
    "disabled",
}

CRITICAL_ROLES = {"primary", "fragile"}
ALLOWED_SOURCE_QUEUES = {"http", "browser"}


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
        normalized = role.strip().lower()
        if normalized in ALLOWED_OPERATIONAL_ROLES:
            return normalized
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
    explicit_role = _manual_role_override(plugin)

    if explicit_role == "disabled":
        return SourceOperationalClassification("disabled", False, "explicit:disabled")
    if not supports_wishlist or explicit_role == "auxiliary":
        return SourceOperationalClassification("auxiliary", False, "auxiliary/feed")
    if not implemented:
        return SourceOperationalClassification("not_implemented", False, "scrape=None")

    if explicit_role:
        include_in_critical = explicit_role in CRITICAL_ROLES
        return SourceOperationalClassification(
            explicit_role,
            include_in_critical,
            f"explicit:{explicit_role}",
        )

    return SourceOperationalClassification("primary", True, "wishlist+implemented+enabled")


def source_operational_severity(role: str | None, enabled: bool = True) -> str:
    if not enabled:
        return "ignored"
    normalized = str(role or "").strip().lower()
    if normalized in {"", "primary"}:
        return "critical"
    if normalized == "fragile":
        return "warning"
    if normalized in {"auxiliary", "experimental", "deprioritized"}:
        return "info"
    if normalized == "disabled":
        return "ignored"
    return "warning"


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


def resolve_source_queue(plugin: SourcePlugin, *, fallback_queue: str = "http") -> str:
    """Resolve queue from source metadata/policy.

    Priority:
    1) explicit `default_extra["queue"]` when valid
    2) `fetch_mode` ("http" or "browser")
    3) fallback queue (sanitized)
    """
    queue_override: Optional[str] = None
    extra = getattr(plugin, "default_extra", None)
    if isinstance(extra, dict):
        raw = extra.get("queue")
        if isinstance(raw, str):
            candidate = raw.strip().lower()
            if candidate in ALLOWED_SOURCE_QUEUES:
                queue_override = candidate

    if queue_override:
        return queue_override

    fetch_mode = str(getattr(plugin, "fetch_mode", "") or "").strip().lower()
    if fetch_mode in ALLOWED_SOURCE_QUEUES:
        return fetch_mode

    normalized_fallback = str(fallback_queue or "http").strip().lower()
    if normalized_fallback in ALLOWED_SOURCE_QUEUES:
        return normalized_fallback
    return "http"
