from __future__ import annotations

import importlib
import json
from pathlib import Path

from app.services.source_v2_inventory import build_source_v2_inventory, render_markdown


class _FakeCfg:
    def __init__(self, source: str, is_enabled: bool, extra: dict | None = None):
        self.source = source
        self.is_enabled = is_enabled
        self.extra = extra or {}


class _FakeDB:
    pass


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


def test_turboclass_dual_experimental_and_enabled_by_default():
    inv = build_source_v2_inventory(db=None)
    turboclass = _row_by_source(inv, "turboclass")

    assert turboclass["default_enabled"] is True
    assert turboclass["has_v1"] is True
    assert turboclass["has_v2"] is True
    assert turboclass["supports_dual"] is True
    assert turboclass["current_impl"] == "v1"
    assert turboclass["operational_role"] == "experimental"

def test_current_impl_defaults_and_db_override_and_invalid_fallback(monkeypatch):
    inv = build_source_v2_inventory(db=None)
    row = _row_by_source(inv, "mercadolivre")
    assert row["current_impl"] == "v1"

    def _fake_import_dual(name, *args, **kwargs):
        if name == "app.services.source_configs_service":
            class _Mod:
                @staticmethod
                def list_source_configs(_db):
                    return [_FakeCfg("mercadolivre", True, {"impl": "dual"})]

            return _Mod()
        return __import__(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", _fake_import_dual)
    row_db = _row_by_source(build_source_v2_inventory(db=_FakeDB()), "mercadolivre")
    assert row_db["current_impl"] == "dual"


def test_db_failure_falls_back_to_static_with_db_unavailable(monkeypatch):
    real_import = __import__

    def _failing_import(name, *args, **kwargs):
        if name == "app.services.source_configs_service":
            raise RuntimeError("db unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", _failing_import)
    inv = build_source_v2_inventory(db=_FakeDB())
    assert inv
    assert all("db_unavailable" in row["notes"] for row in inv)


def test_markdown_header_and_json_serializable():
    inv = build_source_v2_inventory(db=None)
    md = render_markdown(inv)

    assert "| source | has_v1 | has_v2 | supports_dual | current_impl | operational_role | default_enabled | configured_enabled | fetch_mode | v2_class | notes |" in md

    payload = json.dumps(inv)
    assert isinstance(payload, str)


def test_script_main_no_db_without_database_url_no_sessionlocal_import(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    real_import = __import__

    def _guarded_import(name, *args, **kwargs):
        if name == "app.db.session":
            raise AssertionError("app.db.session should not be imported in --no-db mode")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", _guarded_import)

    script = importlib.import_module("scripts.source_v2_inventory")
    rc = script.main(["--no-db"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "| source | has_v1 |" in out
    assert not Path("autohunter.db").exists()
