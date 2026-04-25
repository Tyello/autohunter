from __future__ import annotations

import pytest

from app.services.source_operational_policy import (
    ALLOWED_OPERATIONAL_ROLES,
    classify_source_operational_role,
    should_include_in_critical_stale,
)
from app.sources.registry import list_sources
from app.sources.types import SourcePlugin

BUILTIN_SOURCE_NAMES = {
    "mercadolivre",
    "olx",
    "chavesnamao",
    "webmotors",
    "gogarage",
    "icarros",
    "mobiauto",
    "kavak",
    "facebook_marketplace",
    "turboclass",
    "turboclass_vendidos",
}


def _assert_plugin_contract(plugin: SourcePlugin) -> None:
    assert plugin.name
    assert plugin.name == plugin.name.lower()
    assert callable(plugin.build_url)
    assert isinstance(plugin.supports_manual_search, bool)
    assert isinstance(plugin.supports_wishlist_monitoring, bool)
    assert plugin.fetch_mode in {"http", "browser"}

    if plugin.supports_wishlist_monitoring:
        assert callable(plugin.scrape), f"{plugin.name} must provide scrape when monitoring wishlist"
        has_sched_default = int(getattr(plugin, "default_sched_minutes", 0) or 0) > 0
        has_sched_setting = bool(getattr(plugin, "sched_minutes_setting", None))
        assert has_sched_default or has_sched_setting, f"{plugin.name} requires coherent schedule seed"

    op_class = classify_source_operational_role(plugin)
    if not plugin.supports_wishlist_monitoring:
        assert op_class.role in {"auxiliary", "disabled"}
        assert should_include_in_critical_stale(plugin, None) is False
    if plugin.scrape is None and plugin.supports_wishlist_monitoring:
        assert op_class.role == "not_implemented"
        assert should_include_in_critical_stale(plugin, None) is False

    role = (plugin.default_extra or {}).get("operational_role") if isinstance(plugin.default_extra, dict) else None
    if role is not None:
        assert role in ALLOWED_OPERATIONAL_ROLES, f"{plugin.name} has invalid operational_role={role}"
    if not plugin.supports_wishlist_monitoring:
        assert role != "primary", f"{plugin.name} without wishlist monitoring cannot be primary"


def test_registered_plugins_contract():
    plugins = list_sources()
    names = [p.name for p in plugins]
    assert len(names) == len(set(names))
    for plugin in plugins:
        _assert_plugin_contract(plugin)


def test_builtin_sources_must_declare_operational_role_explicitly():
    plugins = {p.name: p for p in list_sources() if p.name in BUILTIN_SOURCE_NAMES}
    assert set(plugins.keys()) == BUILTIN_SOURCE_NAMES
    for name, plugin in plugins.items():
        assert isinstance(plugin.default_extra, dict), f"{name} must define default_extra as dict"
        assert "operational_role" in plugin.default_extra, f"{name} must declare operational_role"
        assert plugin.default_extra["operational_role"] in ALLOWED_OPERATIONAL_ROLES


def test_builtin_role_specific_expectations():
    by_name = {p.name: p for p in list_sources()}
    assert by_name["turboclass_vendidos"].default_extra["operational_role"] == "auxiliary"
    assert by_name["webmotors"].default_extra["operational_role"] in {"fragile", "deprioritized"}


@pytest.mark.parametrize("role", ["auxiliary", "deprioritized", "disabled"])
def test_non_critical_roles_are_not_included_in_critical_stale(role: str):
    plugin = SourcePlugin(
        name=f"role_{role}",
        build_url=lambda _q: "https://example.com",
        scrape=lambda _u, _ctx: [],
        supports_manual_search=True,
        supports_wishlist_monitoring=True,
        fetch_mode="http",
        default_extra={"operational_role": role},
    )
    assert classify_source_operational_role(plugin).role == role
    assert should_include_in_critical_stale(plugin) is False


def test_missing_role_uses_safe_fallback_in_helper():
    plugin = SourcePlugin(
        name="fallback_source",
        build_url=lambda _q: "https://example.com",
        scrape=lambda _u, _ctx: [],
        supports_manual_search=True,
        supports_wishlist_monitoring=True,
        fetch_mode="http",
    )
    op_class = classify_source_operational_role(plugin)
    assert op_class.role == "primary"
    assert should_include_in_critical_stale(plugin) is True


def test_contract_rejects_malformed_new_plugin():
    malformed = SourcePlugin(
        name="BadSource",
        build_url=lambda _q: "https://example.com",
        scrape=None,
        supports_manual_search=True,
        supports_wishlist_monitoring=True,
        fetch_mode="http",
        default_sched_minutes=0,
    )
    with pytest.raises(AssertionError):
        _assert_plugin_contract(malformed)
