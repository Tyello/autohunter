from __future__ import annotations

import importlib.util
import builtins
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_module(name: str, rel_path: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel_path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_backup_validate_database_url_accepts_postgres(monkeypatch):
    mod = _load_module("backup_core_data_test", "scripts/backup_core_data.py")
    monkeypatch.setattr(mod.settings, "database_url", "postgresql://user:pass@localhost/db", raising=False)

    assert mod._validate_database_url().startswith("postgresql://")


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
    backup.write_text('{"data": {"users": []}}', encoding="utf-8")

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

    class _NoopEngine:
        def begin(self):
            return _NoopConn()

    monkeypatch.setattr(mod, "create_engine", lambda *_args, **_kwargs: _NoopEngine())

    rc = mod.main()
    assert rc == 0
    assert any("Modo: DRY-RUN" in line for line in out)
