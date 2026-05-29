from __future__ import annotations

import builtins
import json
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


def test_compare_validate_database_url_rejects_sqlite(monkeypatch):
    mod = _load_module("compare_core_backup_reject_sqlite", "scripts/compare_core_backup_to_db.py")
    monkeypatch.setattr(mod.settings, "database_url", "sqlite:///tmp.db", raising=False)

    try:
        mod._validate_database_url()
        raise AssertionError("expected SystemExit")
    except SystemExit as exc:
        assert "SQLite" in str(exc)


def test_compare_requires_expected_tables_in_backup():
    mod = _load_module("compare_core_backup_missing_table", "scripts/compare_core_backup_to_db.py")
    payload = {
        "meta": {
            "table_row_counts": {
                "users": 1,
                "wishlists": 1,
            }
        }
    }

    try:
        mod._required_tables_from_backup(payload)
        raise AssertionError("expected SystemExit")
    except SystemExit as exc:
        assert "tabelas obrigatórias" in str(exc)


def test_compare_calculates_diff_correctly():
    mod = _load_module("compare_core_backup_diff", "scripts/compare_core_backup_to_db.py")
    payload = {
        "meta": {
            "table_row_counts": {
                "users": 2,
                "wishlists": 2,
                "wishlist_filters": 1,
                "wishlist_tracked_listings": 3,
                "car_listings": 1,
            }
        }
    }
    db_counts = {
        "users": 2,
        "wishlists": 3,
        "wishlist_filters": 1,
        "wishlist_tracked_listings": 0,
        "car_listings": 1,
    }

    report = mod.compare_backup_to_db(payload, db_counts)
    by_table = {row["table"]: row for row in report.rows}

    assert by_table["users"]["diff"] == 0
    assert by_table["wishlists"]["diff"] == 1
    assert by_table["wishlist_tracked_listings"]["diff"] == -3
    assert not report.ok


def test_restore_apply_prints_final_status_and_is_idempotent_in_report(monkeypatch, tmp_path):
    mod = _load_module("restore_core_data_apply_status", "scripts/restore_core_data.py")
    monkeypatch.setattr(mod.settings, "database_url", "postgresql://user:pass@localhost/db", raising=False)

    backup = tmp_path / "backup.json"
    backup.write_text(
        json.dumps(
            {
                "meta": {"created_at_utc": "2026-04-25T00:00:00Z"},
                "data": {
                    "users": [{"id": 1}],
                    "wishlists": [{"id": 10, "user_id": 1}],
                    "wishlist_filters": [],
                    "wishlist_tracked_listings": [],
                },
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        mod.argparse.ArgumentParser,
        "parse_args",
        lambda _self: type("Args", (), {"input": str(backup), "apply": True})(),
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

    inserted_values = [1, 1, 0, 0]

    def _insert(*_args, **_kwargs):
        return inserted_values.pop(0)

    monkeypatch.setattr(mod, "_insert_on_conflict_do_nothing", _insert)

    rc_first = mod.main()
    assert rc_first == 0
    assert any("Status final: success" in line for line in out)

    out.clear()
    inserted_values[:] = [0, 0, 0, 0]
    rc_second = mod.main()
    assert rc_second == 0
    assert any("Status final: success_with_skips" in line for line in out)

import gzip
import subprocess
import sys


def _write_sql_gz(path: Path, blocks: dict[tuple[str, str], list[str]], extra_sql: str = "") -> Path:
    lines: list[str] = []
    if extra_sql:
        lines.extend(extra_sql.strip().splitlines())
    for (schema, table), rows in blocks.items():
        lines.append(f"COPY {schema}.{table} (id) FROM stdin;")
        lines.extend(rows)
        lines.append("\\.")
        lines.append("")
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    return path


def test_inspect_backup_dump_counts_copy_blocks(tmp_path):
    mod = _load_module("inspect_backup_dump_counts", "scripts/backup_dump_utils.py")
    backup = _write_sql_gz(
        tmp_path / "healthy.sql.gz",
        {
            ("public", "users"): ["1"],
            ("public", "wishlists"): ["10", "11"],
            ("public", "wishlist_filters"): ["100"],
            ("public", "source_configs"): ["200", "201", "202"],
            ("public", "scrape_jobs"): ["300", "301", "302", "303"],
            ("auth", "users"): ["do-not-count"],
        },
    )

    report = mod.inspect_dump(backup)

    assert report.counts["users"] == 1
    assert report.counts["wishlists"] == 2
    assert report.counts["wishlist_filters"] == 1
    assert report.counts["source_configs"] == 3
    assert report.counts["scrape_jobs"] == 4
    assert report.present["users"]
    assert report.ok


def test_inspect_backup_dump_fails_when_users_zero(tmp_path):
    mod = _load_module("inspect_backup_dump_users_zero", "scripts/backup_dump_utils.py")
    backup = _write_sql_gz(
        tmp_path / "no_users.sql.gz",
        {
            ("public", "users"): [],
            ("public", "wishlists"): ["10"],
            ("public", "source_configs"): ["200"],
        },
    )

    report = mod.inspect_dump(backup)

    assert not report.ok
    assert "users=0" in report.failed_requirements()


def test_inspect_backup_dump_fails_when_wishlists_zero(tmp_path):
    mod = _load_module("inspect_backup_dump_wishlists_zero", "scripts/backup_dump_utils.py")
    backup = _write_sql_gz(
        tmp_path / "no_wishlists.sql.gz",
        {
            ("public", "users"): ["1"],
            ("public", "wishlists"): [],
            ("public", "source_configs"): ["200"],
        },
    )

    report = mod.inspect_dump(backup)

    assert not report.ok
    assert "wishlists=0" in report.failed_requirements()


def test_inspect_backup_dump_fails_for_invalid_gzip(tmp_path):
    backup = tmp_path / "invalid.sql.gz"
    backup.write_text("not really gzip", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/inspect_backup_dump.py"), str(backup)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "invalid backup dump" in result.stderr or "unable to read backup" in result.stderr


def test_extract_core_restore_sql_only_allowed_tables(tmp_path):
    sys.path.insert(0, str(ROOT / "scripts"))
    mod = _load_module("extract_core_restore_only_allowed", "scripts/extract_core_restore_sql.py")
    backup = _write_sql_gz(
        tmp_path / "mixed.sql.gz",
        {
            ("public", "source_configs"): ["source-config-should-not-restore"],
            ("public", "users"): ["1"],
            ("public", "wishlists"): ["10"],
            ("public", "wishlist_filters"): ["100"],
            ("public", "notifications"): ["900"],
            ("auth", "users"): ["auth-user"],
            ("storage", "objects"): ["object"],
            ("extensions", "pg_stat_statements"): ["extension"],
        },
        extra_sql="""
        CREATE TABLE public.users (id integer);
        CREATE INDEX idx_users_id ON public.users (id);
        ALTER TABLE public.users ADD CONSTRAINT users_pkey PRIMARY KEY (id);
        DROP TABLE public.old_table;
        TRUNCATE public.users;
        """,
    )

    sql = mod.render_restore_sql(backup)

    assert "COPY public.users" in sql
    assert "COPY public.wishlists" in sql
    assert "COPY public.wishlist_filters" in sql
    assert "COPY public.notifications" in sql
    assert "source-config-should-not-restore" not in sql
    assert "COPY auth." not in sql
    assert "COPY storage." not in sql
    assert "COPY extensions." not in sql


def test_extract_core_restore_sql_preserves_safe_order(tmp_path):
    sys.path.insert(0, str(ROOT / "scripts"))
    mod = _load_module("extract_core_restore_order", "scripts/extract_core_restore_sql.py")
    backup = _write_sql_gz(
        tmp_path / "unordered.sql.gz",
        {
            ("public", "notifications"): ["900"],
            ("public", "wishlist_filters"): ["100"],
            ("public", "wishlists"): ["10"],
            ("public", "users"): ["1"],
            ("public", "account_members"): ["2"],
            ("public", "wishlist_tokens"): ["101"],
            ("public", "wishlist_tracked_listings"): ["102"],
            ("public", "wishlist_listing_activity"): ["103"],
            ("public", "user_digest_preferences"): ["104"],
        },
    )

    sql = mod.render_restore_sql(backup)

    positions = [sql.index(f"COPY public.{table}") for table in mod.CORE_RESTORE_TABLES]
    assert positions == sorted(positions)


def test_extract_core_restore_sql_excludes_ddl_and_destructive_statements(tmp_path):
    sys.path.insert(0, str(ROOT / "scripts"))
    mod = _load_module("extract_core_restore_no_ddl", "scripts/extract_core_restore_sql.py")
    backup = _write_sql_gz(
        tmp_path / "ddl.sql.gz",
        {("public", "users"): ["1"], ("public", "wishlists"): ["10"]},
        extra_sql="""
        CREATE TABLE public.users (id integer);
        CREATE INDEX idx_users_id ON public.users (id);
        ALTER TABLE public.users ADD COLUMN name text;
        DROP TABLE public.anything;
        TRUNCATE public.users;
        """,
    )

    sql = mod.render_restore_sql(backup).upper()

    assert "CREATE TABLE" not in sql
    assert "CREATE INDEX" not in sql
    assert "ALTER TABLE" not in sql
    assert "DROP " not in sql
    assert "TRUNCATE" not in sql


def test_backup_dump_scripts_do_not_require_database_url(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    backup = _write_sql_gz(
        tmp_path / "healthy.sql.gz",
        {
            ("public", "users"): ["1"],
            ("public", "wishlists"): ["10"],
            ("public", "source_configs"): ["200"],
        },
    )

    inspect_result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/inspect_backup_dump.py"), str(backup)],
        text=True,
        capture_output=True,
        check=False,
    )
    output = tmp_path / "core_restore.sql"
    extract_result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/extract_core_restore_sql.py"), str(backup), "--output", str(output)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert inspect_result.returncode == 0
    assert extract_result.returncode == 0
    assert output.exists()
    assert "DATABASE_URL" not in inspect_result.stdout
    assert "DATABASE_URL" not in inspect_result.stderr
    assert "DATABASE_URL" not in extract_result.stdout
    assert "DATABASE_URL" not in extract_result.stderr
