import importlib.util


def _load():
    spec = importlib.util.spec_from_file_location("import_fipe_catalog_entries_test", "scripts/import_fipe_catalog_entries.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_json_dry_run_apply_and_missing_file(tmp_path):
    mod = _load()
    f = tmp_path / "rows.json"
    f.write_text('[{"model_name":"Civic","price":100000}]', encoding="utf-8")
    assert mod.main(["--file", str(f), "--reference-month", "2026-05"]) == 0
    assert mod.main(["--file", str(f), "--reference-month", "2026-05", "--apply"]) == 0
    assert mod.main(["--file", str(tmp_path / "missing.json"), "--reference-month", "2026-05"]) != 0


def test_csv_and_zero_valid(tmp_path):
    mod = _load()
    f = tmp_path / "rows.csv"
    f.write_text("model_name,price\nCivic,100000\n", encoding="utf-8")
    assert mod.main(["--file", str(f), "--reference-month", "2026-05"]) == 0
    bad = tmp_path / "bad.csv"
    bad.write_text("model_name,price\n,0\n", encoding="utf-8")
    assert mod.main(["--file", str(bad), "--reference-month", "2026-05", "--apply"]) != 0
