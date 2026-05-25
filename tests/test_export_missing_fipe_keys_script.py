import csv
import importlib.util


def _load():
    spec = importlib.util.spec_from_file_location("export_missing_fipe_keys_test", "scripts/export_missing_fipe_keys.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_export_missing_keys_generates_csv_and_force_flag(tmp_path, monkeypatch, db):
    mod = _load()

    calls = {"count": 0}

    def _fake_report(_db, reference_month=None, limit=20):
        calls["count"] += 1
        return {
            "reference_month": reference_month or "2026-05",
            "top_missing_keys": [
                {"vehicle_key": "honda|civic|2015", "count": 18},
                {"vehicle_key": "volkswagen|golf|2017", "count": 10},
            ],
        }

    monkeypatch.setattr(mod, "build_fipe_coverage_report", _fake_report)

    out = tmp_path / "missing.csv"
    assert mod.main(["--reference-month", "2026-05", "--output", str(out), "--limit", "2"]) == 0
    assert calls["count"] == 1

    with out.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    assert len(rows) == 2
    assert rows[0]["vehicle_key"] == "honda|civic|2015"
    assert rows[0]["listings_count"] == "18"
    assert rows[0]["reference_month"] == "2026-05"
    assert rows[0]["fipe_price"] == ""
    assert rows[0]["currency"] == "BRL"

    assert mod.main(["--reference-month", "2026-05", "--output", str(out)]) == 1
    assert mod.main(["--reference-month", "2026-05", "--output", str(out), "--force"]) == 0
