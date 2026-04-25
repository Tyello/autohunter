from __future__ import annotations

import builtins
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_module(name: str, rel_path: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel_path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_backup_validate_database_url_rejects_sqlite(monkeypatch):
    mod = _load_module("backup_core_data_reject_sqlite_test", "scripts/backup_core_data.py")
    monkeypatch.setattr(mod.settings, "database_url", "sqlite:///tmp.db", raising=False)

    try:
        mod._validate_database_url()
        raise AssertionError("expected SystemExit")
    except SystemExit as exc:
        assert "PostgreSQL/Supabase" in str(exc)


def test_restore_validate_database_url_rejects_non_postgres(monkeypatch):
    mod = _load_module("restore_core_data_test", "scripts/restore_core_data.py")
    monkeypatch.setattr(mod.settings, "database_url", "sqlite:///tmp.db", raising=False)

    try:
        mod._validate_database_url()
        raise AssertionError("expected SystemExit")
    except SystemExit as exc:
        assert "PostgreSQL/Supabase" in str(exc)


def test_restore_is_dry_run_by_default(monkeypatch, tmp_path):
    mod = _load_module("restore_core_data_dryrun_test", "scripts/restore_core_data.py")
    monkeypatch.setattr(mod.settings, "database_url", "postgresql://user:pass@localhost/db", raising=False)

    backup = tmp_path / "backup.json"
    backup.write_text('{"meta": {"created_at_utc": "2026-04-25T00:00:00Z"}, "data": {"users": []}}', encoding="utf-8")

    monkeypatch.setattr(
        mod.argparse.ArgumentParser,
        "parse_args",
        lambda _self: type("Args", (), {"input": str(backup), "apply": False})(),
    )

    out = []
    monkeypatch.setattr(builtins, "print", lambda *args, **kwargs: out.append(" ".join(str(a) for a in args)))

    class _NoopConn:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, *_args, **_kwargs):
            return type("_Res", (), {"mappings": lambda self: type("_Map", (), {"all": lambda self: []})()})()

    class _NoopEngine:
        def begin(self):
            return _NoopConn()

    monkeypatch.setattr(mod, "create_engine", lambda *_args, **_kwargs: _NoopEngine())
    monkeypatch.setattr(mod, "_table_exists", lambda *_args, **_kwargs: True)

    rc = mod.main()
    assert rc == 0
    assert any("Modo: DRY-RUN" in line for line in out)


def test_restore_requires_explicit_apply_flag(monkeypatch, tmp_path):
    mod = _load_module("restore_core_data_apply_flag_test", "scripts/restore_core_data.py")
    monkeypatch.setattr(mod.settings, "database_url", "postgresql://user:pass@localhost/db", raising=False)

    backup = tmp_path / "backup.json"
    backup.write_text(
        '{"meta": {"created_at_utc": "2026-04-25T00:00:00Z"}, "data": {"users": [{"id": 1}]}}',
        encoding="utf-8",
    )

    monkeypatch.setattr(
        mod.argparse.ArgumentParser,
        "parse_args",
        lambda _self: type("Args", (), {"input": str(backup), "apply": False})(),
    )

    inserted_calls = []

    def _fail_if_called(*_args, **_kwargs):
        inserted_calls.append(True)
        raise AssertionError("should not insert in dry-run")

    monkeypatch.setattr(mod, "_insert_on_conflict_do_nothing", _fail_if_called)

    class _NoopConn:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, *_args, **_kwargs):
            return type("_Res", (), {"mappings": lambda self: type("_Map", (), {"all": lambda self: []})()})()

    class _NoopEngine:
        def begin(self):
            return _NoopConn()

    monkeypatch.setattr(mod, "create_engine", lambda *_args, **_kwargs: _NoopEngine())
    monkeypatch.setattr(mod, "_table_exists", lambda *_args, **_kwargs: True)

    assert mod.main() == 0
    assert not inserted_calls


def test_validate_core_backup_accepts_minimal_valid_payload():
    mod = _load_module("validate_core_backup_valid", "scripts/validate_core_backup.py")

    payload = {
        "meta": {"created_at_utc": "2026-04-25T00:00:00Z", "tables": ["users", "wishlists"]},
        "data": {
            "users": [{"id": 1}],
            "wishlists": [{"id": 10, "user_id": 1}],
            "wishlist_filters": [{"id": 100, "wishlist_id": 10}],
            "wishlist_tracked_listings": [{"id": 200, "wishlist_id": 10, "car_listing_id": None}],
        },
    }

    report = mod.validate_payload(payload)
    assert report.is_valid


def test_validate_core_backup_rejects_missing_expected_tables():
    mod = _load_module("validate_core_backup_missing_tables", "scripts/validate_core_backup.py")

    payload = {"meta": {"created_at_utc": "2026-04-25T00:00:00Z", "tables": []}, "data": {"users": []}}
    report = mod.validate_payload(payload)

    assert not report.is_valid
    assert any("Tabelas obrigatórias ausentes" in err for err in report.errors)


def test_validate_core_backup_detects_wishlist_without_user():
    mod = _load_module("validate_core_backup_bad_wishlist", "scripts/validate_core_backup.py")

    payload = {
        "meta": {"created_at_utc": "2026-04-25T00:00:00Z", "tables": []},
        "data": {
            "users": [{"id": 1}],
            "wishlists": [{"id": 10, "user_id": 999}],
            "wishlist_filters": [],
            "wishlist_tracked_listings": [],
        },
    }

    report = mod.validate_payload(payload)
    assert not report.is_valid
    assert any("referencia user_id ausente" in err for err in report.errors)


def test_validate_core_backup_detects_filter_without_wishlist():
    mod = _load_module("validate_core_backup_bad_filter", "scripts/validate_core_backup.py")

    payload = {
        "meta": {"created_at_utc": "2026-04-25T00:00:00Z", "tables": []},
        "data": {
            "users": [{"id": 1}],
            "wishlists": [{"id": 10, "user_id": 1}],
            "wishlist_filters": [{"id": 100, "wishlist_id": 999}],
            "wishlist_tracked_listings": [],
        },
    }

    report = mod.validate_payload(payload)
    assert not report.is_valid
    assert any("referencia wishlist_id ausente" in err for err in report.errors)


def test_validate_core_backup_allows_null_car_listing_id():
    mod = _load_module("validate_core_backup_null_car_listing", "scripts/validate_core_backup.py")

    payload = {
        "meta": {"created_at_utc": "2026-04-25T00:00:00Z", "tables": []},
        "data": {
            "users": [{"id": 1}],
            "wishlists": [{"id": 10, "user_id": 1}],
            "wishlist_filters": [{"id": 100, "wishlist_id": 10}],
            "wishlist_tracked_listings": [{"id": 200, "wishlist_id": 10, "car_listing_id": None}],
            "car_listings": [],
        },
    }

    report = mod.validate_payload(payload)
    assert report.is_valid
