import csv
from pathlib import Path


def test_fipe_template_exists_with_required_columns():
    path = Path("docs/examples/fipe_prices_template.csv")
    assert path.exists()

    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        assert set(reader.fieldnames or []) == {"vehicle_key", "fipe_price", "reference_month", "currency"}


def test_fipe_operational_doc_mentions_required_commands():
    text = Path("docs/FIPE_OPERATIONAL_LOAD.md").read_text(encoding="utf-8")
    assert "/admin fipe coverage" in text
    assert "/admin fipe coverage 2026-05 50" in text
    assert "python scripts/import_fipe_prices.py --file docs/examples/fipe_prices_template.csv --reference-month 2026-05" in text
    assert "python scripts/import_fipe_prices.py --file caminho/real/fipe_prices.csv --reference-month 2026-05 --apply" in text
