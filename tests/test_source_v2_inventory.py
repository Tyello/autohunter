from __future__ import annotations

import json

from app.services.source_v2_inventory import build_source_v2_inventory, render_markdown


class _FakeCfg:
    def __init__(self, source: str, is_enabled: bool, extra: dict | None = None):
        self.source = source
        self.is_enabled = is_enabled
        self.extra = extra or {}


class _FakeDB:
    def __init__(self, rows: list[_FakeCfg]):
        self._rows = rows


def _row_by_source(inv: list[dict], source: str) -> dict:
    return next(row for row in inv if row["source"] == source)


def test_static_inventory_without_db_contains_expected_sources_and_keys():
    inv = build_source_v2_inventory(db=None)
    assert isinstance(inv, list)

    sources = {row["source"] for row in inv}
    assert "mercadolivre" in sources
    assert "olx" in sources
    assert "webmotors" in sources
    assert "facebook_marketplace" in sources

    required = {
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
    }
    for row in inv:
        assert required.issubset(row.keys())


def test_v1_v2_detection_and_dual_support_logic():
    inv = build_source_v2_inventory(db=None)

    mercadolivre = _row_by_source(inv, "mercadolivre")
    assert mercadolivre["has_v1"] is True
    assert mercadolivre["has_v2"] is True

    facebook = _row_by_source(inv, "facebook_marketplace")
    assert facebook["has_v1"] is True
    assert facebook["has_v2"] is False

    for row in inv:
        assert row["supports_dual"] == (row["has_v1"] and row["has_v2"])


def test_webmotors_is_deprioritized_disabled_and_noted():
    inv = build_source_v2_inventory(db=None)
    webmotors = _row_by_source(inv, "webmotors")

    assert webmotors["operational_role"] == "deprioritized"
    assert webmotors["default_enabled"] is False
    assert webmotors["has_v2"] is True
    assert "deprioritized" in webmotors["notes"]


def test_current_impl_defaults_and_db_override_and_invalid_fallback(monkeypatch):
    inv = build_source_v2_inventory(db=None)
    row = _row_by_source(inv, "mercadolivre")
    assert row["current_impl"] == "v1"

    def _fake_list_source_configs(_db):
        return [_FakeCfg("mercadolivre", True, {"impl": "dual"})]

    monkeypatch.setattr("app.services.source_v2_inventory.list_source_configs", _fake_list_source_configs)
    inv_db = build_source_v2_inventory(db=_FakeDB([]))
    row_db = _row_by_source(inv_db, "mercadolivre")
    assert row_db["current_impl"] == "dual"

    def _fake_invalid_impl(_db):
        return [_FakeCfg("mercadolivre", True, {"impl": "invalid"})]

    monkeypatch.setattr("app.services.source_v2_inventory.list_source_configs", _fake_invalid_impl)
    inv_invalid = build_source_v2_inventory(db=_FakeDB([]))
    row_invalid = _row_by_source(inv_invalid, "mercadolivre")
    assert row_invalid["current_impl"] == "v1"


def test_markdown_header_and_json_serializable():
    inv = build_source_v2_inventory(db=None)
    md = render_markdown(inv)

    assert "| source | has_v1 | has_v2 | supports_dual | current_impl | operational_role | default_enabled | configured_enabled | fetch_mode | v2_class | notes |" in md

    payload = json.dumps(inv)
    assert isinstance(payload, str)
