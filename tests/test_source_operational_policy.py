from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.services.source_operational_policy import (
    ALLOWED_OPERATIONAL_ROLES,
    classify_source_operational_role,
    should_include_in_critical_stale,
    source_operational_hint,
)
from app.sources.types import SourcePlugin


def _plugin(**kwargs) -> SourcePlugin:
    data = dict(
        name="olx",
        build_url=lambda _q: "https://example.com",
        scrape=lambda _u, _ctx: [],
        supports_wishlist_monitoring=True,
        supports_manual_search=True,
        fetch_mode="http",
    )
    data.update(kwargs)
    return SourcePlugin(**data)


def test_primary_enabled_source_included_in_critical_stale():
    plugin = _plugin()
    cfg = SimpleNamespace(is_enabled=True)
    op = classify_source_operational_role(plugin, cfg=cfg)
    assert op.role == "primary"
    assert should_include_in_critical_stale(plugin, cfg=cfg) is True


def test_disabled_source_not_included_in_critical_stale():
    plugin = _plugin()
    cfg = SimpleNamespace(is_enabled=False)
    op = classify_source_operational_role(plugin, cfg=cfg)
    assert op.role == "disabled"
    assert should_include_in_critical_stale(plugin, cfg=cfg) is False


def test_auxiliary_source_not_included_in_critical_stale():
    plugin = _plugin(name="feed", supports_wishlist_monitoring=False)
    op = classify_source_operational_role(plugin, cfg=SimpleNamespace(is_enabled=True))
    assert op.role == "auxiliary"
    assert should_include_in_critical_stale(plugin, cfg=SimpleNamespace(is_enabled=True)) is False


def test_not_implemented_source_not_included_in_critical_stale():
    plugin = _plugin(name="new_source", scrape=None)
    op = classify_source_operational_role(plugin, cfg=SimpleNamespace(is_enabled=True))
    assert op.role == "not_implemented"
    assert should_include_in_critical_stale(plugin, cfg=SimpleNamespace(is_enabled=True)) is False


def test_explicit_fragile_is_included_in_critical_stale():
    plugin = _plugin(default_extra={"operational_role": "fragile"})
    op = classify_source_operational_role(plugin, cfg=SimpleNamespace(is_enabled=True))
    assert op.role == "fragile"
    assert should_include_in_critical_stale(plugin, cfg=SimpleNamespace(is_enabled=True)) is True


def test_explicit_experimental_is_not_included_in_critical_stale():
    plugin = _plugin(default_extra={"operational_role": "experimental"})
    op = classify_source_operational_role(plugin, cfg=SimpleNamespace(is_enabled=True))
    assert op.role == "experimental"
    assert should_include_in_critical_stale(plugin, cfg=SimpleNamespace(is_enabled=True)) is False
    assert source_operational_hint(plugin, state=SimpleNamespace(last_status="blocked")) is None


def test_explicit_deprioritized_is_not_included_in_critical_stale():
    plugin = _plugin(default_extra={"operational_role": "deprioritized"})
    op = classify_source_operational_role(plugin, cfg=SimpleNamespace(is_enabled=True))
    assert op.role == "deprioritized"
    assert should_include_in_critical_stale(plugin, cfg=SimpleNamespace(is_enabled=True)) is False


def test_invalid_explicit_role_falls_back_to_primary_when_enabled():
    plugin = _plugin(default_extra={"operational_role": "unknown"})
    op = classify_source_operational_role(plugin, cfg=SimpleNamespace(is_enabled=True))
    assert "unknown" not in ALLOWED_OPERATIONAL_ROLES
    assert op.role == "primary"
    assert should_include_in_critical_stale(plugin, cfg=SimpleNamespace(is_enabled=True)) is True


def test_webmotors_blocked_state_receives_antibot_hint():
    plugin = _plugin(name="webmotors")
    state = SimpleNamespace(
        last_status="blocked",
        next_allowed_at=datetime.now(timezone.utc) + timedelta(minutes=60),
    )
    hint = source_operational_hint(plugin, state=state)
    assert hint is not None
    assert "anti-bot" in hint
