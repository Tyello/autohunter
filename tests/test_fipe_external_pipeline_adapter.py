from app.services.fipe_external_pipeline_adapter import normalize_external_fipe_row, normalize_external_fipe_rows


def test_adapter_portuguese_aliases():
    row = {
        "marca": "Honda",
        "codigo_marca": "25",
        "modelo": "Civic",
        "codigo_modelo": "4828",
        "ano": "2015",
        "codigo_fipe": "015088-6",
        "valor": "R$ 95.000,00",
    }
    out = normalize_external_fipe_row(row, reference_month="2026-05")
    assert out["brand_name"] == "Honda"
    assert out["model_name"] == "Civic"
    assert out["price"] == 95000
    assert out["model_year"] == 2015
    assert out["fipe_code"] == "015088-6"


def test_adapter_english_aliases_and_raw_payload():
    row = {"brand_name": "Toyota", "model_name": "Corolla", "price": "123000", "model_year": 2020}
    out = normalize_external_fipe_row(row, reference_month="2026-05")
    assert out["brand_name"] == "Toyota"
    assert out["model_name"] == "Corolla"
    assert out["price"] == 123000
    assert out["raw_payload"] == row


def test_adapter_skips_missing_model_and_price():
    rows = [{"price": "10"}, {"model_name": "X"}, {"model_name": "Y", "price": "10"}]
    out, counters = normalize_external_fipe_rows(rows, reference_month="2026-05")
    assert len(out) == 1
    assert counters["skipped_missing_model"] == 1
    assert counters["skipped_missing_price"] == 1
