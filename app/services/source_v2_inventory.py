from __future__ import annotations

from typing import Any

from app.scrapers.sources import list_scrapers
from app.sources.flags import read_source_impl_flags
from app.sources.registry import list_sources
from app.services.source_configs_service import list_source_configs


REQUIRED_COLUMNS = [
    "source",
    "has_v1",
    "has_v2",
    "supports_dual",
    "current_impl",
    "operational_role",
    "default_enabled",
    "configured_enabled",
    "fetch_mode",
    "v2_registered",
    "v2_class",
    "notes",
]


def _normalize_extra(extra: Any) -> dict[str, Any]:
    return dict(extra) if isinstance(extra, dict) else {}


def _build_config_index(db: Any) -> tuple[dict[str, Any], bool]:
    if db is None:
        return {}, False

    rows = list_source_configs(db)
    return {str(row.source).strip().lower(): row for row in rows}, True


def build_source_v2_inventory(db: Any = None) -> list[dict[str, Any]]:
    """Builds a source coverage inventory for V1/V2 implementation paths.

    The function is intentionally read-only and can run without DB access.
    """
    config_by_source, db_available = _build_config_index(db)
    v2_scrapers = list_scrapers()

    inventory: list[dict[str, Any]] = []
    for plugin in sorted(list_sources(), key=lambda p: p.name):
        source = str(plugin.name).strip().lower()
        cfg = config_by_source.get(source)

        default_extra = _normalize_extra(getattr(plugin, "default_extra", None))
        cfg_extra = _normalize_extra(getattr(cfg, "extra", None)) if cfg else {}
        flags = read_source_impl_flags(cfg_extra if cfg else default_extra)

        has_v1 = callable(getattr(plugin, "scrape", None))
        has_v2 = source in v2_scrapers
        supports_dual = has_v1 and has_v2

        default_enabled = bool(getattr(plugin, "default_enabled", True))
        configured_enabled = bool(cfg.is_enabled) if cfg else None

        operational_role = (
            str(cfg_extra.get("operational_role")).strip()
            if cfg and cfg_extra.get("operational_role")
            else str(default_extra.get("operational_role")).strip()
            if default_extra.get("operational_role")
            else "primary" if has_v1 and default_enabled else "unknown"
        )

        v2_obj = v2_scrapers.get(source)
        v2_class = v2_obj.__class__.__name__ if v2_obj is not None else "-"

        notes: list[str] = []
        if not has_v1:
            notes.append("no_v1_scraper")
        if not has_v2:
            notes.append("no_v2_registered")
        if supports_dual:
            notes.append("dual_supported")
        if not db_available:
            notes.append("db_unavailable")
        elif cfg is None:
            notes.append("db_config_missing")
        if operational_role in {"deprioritized", "experimental"}:
            notes.append(operational_role)
        if not default_enabled:
            notes.append("disabled_by_default")

        inventory.append(
            {
                "source": source,
                "has_v1": has_v1,
                "has_v2": has_v2,
                "supports_dual": supports_dual,
                "current_impl": flags.impl,
                "operational_role": operational_role,
                "default_enabled": default_enabled,
                "configured_enabled": configured_enabled,
                "fetch_mode": getattr(plugin, "fetch_mode", "-") or "-",
                "v2_registered": has_v2,
                "v2_class": v2_class,
                "notes": notes,
            }
        )

    return inventory


def render_markdown(inventory: list[dict[str, Any]]) -> str:
    header = "| source | has_v1 | has_v2 | supports_dual | current_impl | operational_role | default_enabled | configured_enabled | fetch_mode | v2_class | notes |"
    sep = "|---|---:|---:|---:|---|---|---:|---:|---|---|---|"
    lines = [header, sep]

    for item in sorted(inventory, key=lambda row: row["source"]):
        notes = ",".join(item.get("notes") or [])
        row = (
            f"| {item['source']} | {int(bool(item['has_v1']))} | {int(bool(item['has_v2']))} | "
            f"{int(bool(item['supports_dual']))} | {item['current_impl']} | {item['operational_role']} | "
            f"{int(bool(item['default_enabled']))} | "
            f"{'-' if item['configured_enabled'] is None else int(bool(item['configured_enabled']))} | "
            f"{item['fetch_mode']} | {item.get('v2_class', '-')} | {notes} |"
        )
        lines.append(row)

    return "\n".join(lines)
