import importlib.util
from pathlib import Path

from app.models.fipe_price import FipePrice


def _load():
    spec = importlib.util.spec_from_file_location("import_fipe_prices_test", "scripts/import_fipe_prices.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_csv_dry_run_and_apply(tmp_path, db):
    csv_file = tmp_path / "fipe.csv"
    csv_file.write_text("vehicle_key,fipe_price\nhonda|civic|2015,100000\n", encoding="utf-8")
    mod = _load()
    assert mod.main(["--file", str(csv_file), "--reference-month", "2026-05"]) == 0
    assert db.query(FipePrice).count() == 0
    assert mod.main(["--file", str(csv_file), "--reference-month", "2026-05", "--apply"]) == 0
    assert db.query(FipePrice).count() == 1


def test_invalid_file_and_zero_valid(tmp_path):
    mod = _load()
    assert mod.main(["--file", str(tmp_path / "missing.csv")]) != 0
    csv_file = tmp_path / "bad.csv"
    csv_file.write_text("vehicle_key,fipe_price\n,0\n", encoding="utf-8")
    assert mod.main(["--file", str(csv_file), "--apply", "--reference-month", "2026-05"]) != 0
