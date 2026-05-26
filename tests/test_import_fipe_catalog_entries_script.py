import importlib.util

from app.models.fipe_catalog_entry import FipeCatalogEntry
from app.models.fipe_sync_run import FipeSyncRun


def _load():
    spec = importlib.util.spec_from_file_location("import_fipe_catalog_entries_test", "scripts/import_fipe_catalog_entries.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_json_dry_run_apply_and_missing_file(tmp_path, db):
    mod = _load()
    f = tmp_path / "rows.json"
    f.write_text('[{"brand_name":"Honda","model_name":"Civic","model_year":2019,"price":100000}]', encoding="utf-8")
    assert mod.main(["--file", str(f), "--reference-month", "2026-05", "--format", "generic"]) == 0
    assert db.query(FipeCatalogEntry).count() == 0
    assert db.query(FipeSyncRun).count() == 0
    assert mod.main(["--file", str(f), "--reference-month", "2026-05", "--format", "generic", "--apply"]) == 0
    assert db.query(FipeCatalogEntry).count() == 1
    assert db.query(FipeSyncRun).count() == 1
    assert db.query(FipeSyncRun).first().status == "completed"
    assert mod.main(["--file", str(tmp_path / "missing.json"), "--reference-month", "2026-05"]) != 0


def test_external_pipeline_dry_run_and_apply(tmp_path, db):
    mod = _load()
    f = tmp_path / "rows.json"
    f.write_text('[{"marca":"Honda","modelo":"Civic","ano":"2019","valor":"R$ 100.000,00"}]', encoding="utf-8")
    assert mod.main(["--file", str(f), "--reference-month", "2026-05", "--format", "external-pipeline"]) == 0
    assert db.query(FipeCatalogEntry).count() == 0
    assert db.query(FipeSyncRun).count() == 0
    assert mod.main(["--file", str(f), "--reference-month", "2026-05", "--format", "external-pipeline", "--apply"]) == 0
    assert db.query(FipeCatalogEntry).count() == 1


def test_invalid_file_and_zero_normalized(tmp_path, db):
    mod = _load()
    bad_json = tmp_path / "bad.json"
    bad_json.write_text('{"x":1}', encoding="utf-8")
    assert mod.main(["--file", str(bad_json), "--reference-month", "2026-05", "--format", "external-pipeline"]) != 0
    empty = tmp_path / "empty.json"
    empty.write_text('[{"marca":"Honda"}]', encoding="utf-8")
    assert mod.main(["--file", str(empty), "--reference-month", "2026-05", "--format", "external-pipeline"]) != 0
    assert db.query(FipeSyncRun).count() == 0
