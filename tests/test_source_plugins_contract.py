from __future__ import annotations

import pytest

from app.services.source_operational_policy import classify_source_operational_role, should_include_in_critical_stale
from app.sources.registry import list_sources
from app.sources.types import SourcePlugin


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


def test_registered_plugins_contract():
    plugins = list_sources()
    names = [p.name for p in plugins]
    assert len(names) == len(set(names))
    for plugin in plugins:
        _assert_plugin_contract(plugin)


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
