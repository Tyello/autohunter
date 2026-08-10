from __future__ import annotations

from unittest.mock import Mock

from app.services.fipe_api_client import FipeApiClient, FipeApiError
from app.services.fipe_catalog_crawler import crawl_latest_fipe_prices
from app.services.fipe_external_pipeline_adapter import normalize_external_fipe_rows


def _one_brand_client():
    client = Mock(spec=FipeApiClient)
    client.get_latest_reference_table.return_value = {"Codigo": 320, "Mes": "agosto/2026"}
    client.get_brands.return_value = [{"Value": "1", "Label": "Toyota"}]
    client.get_models.return_value = [{"Value": "100", "Label": "Corolla"}]
    client.get_model_years.return_value = [{"Value": "2020-1", "Label": "2020 Gasolina"}]
    client.get_price.return_value = {
        "Valor": "R$ 95.000,00",
        "Marca": "Toyota",
        "Modelo": "Corolla",
        "AnoModelo": 2020,
        "Combustivel": "Gasolina",
        "CodigoFipe": "001004-9",
        "MesReferencia": "agosto de 2026 ",
        "TipoVeiculo": 1,
        "SiglaCombustivel": "G",
    }
    return client


def test_crawl_output_shape_matches_adapter():
    client = _one_brand_client()

    rows = crawl_latest_fipe_prices(client)

    assert len(rows) == 1
    row = rows[0]
    assert set(row.keys()) == {"tipo_veiculo", "marca", "modelo", "ano", "combustivel", "codigo_fipe", "valor"}

    normalized, stats = normalize_external_fipe_rows(rows, reference_month="2026-08")

    assert stats.get("skipped_invalid", 0) == 0
    assert len(normalized) == 1


def test_limit_brands_bounds_crawl():
    client = Mock(spec=FipeApiClient)
    client.get_latest_reference_table.return_value = {"Codigo": 320, "Mes": "agosto/2026"}
    client.get_brands.return_value = [{"Value": str(i), "Label": f"Brand{i}"} for i in range(5)]
    client.get_models.return_value = []

    crawl_latest_fipe_prices(client, limit_brands=2)

    assert client.get_models.call_count == 2


def test_individual_combination_error_does_not_abort_crawl():
    client = Mock(spec=FipeApiClient)
    client.get_latest_reference_table.return_value = {"Codigo": 320, "Mes": "agosto/2026"}
    client.get_brands.return_value = [{"Value": "1", "Label": "Toyota"}]
    client.get_models.return_value = [{"Value": "100", "Label": "Corolla"}]
    client.get_model_years.return_value = [
        {"Value": "2019-1", "Label": "2019"},
        {"Value": "2020-1", "Label": "2020"},
    ]

    def price_side_effect(**kwargs):
        if kwargs["model_year"] == 2019:
            raise FipeApiError("boom")
        return {
            "Valor": "R$ 90.000,00",
            "Marca": "Toyota",
            "Modelo": "Corolla",
            "AnoModelo": 2020,
            "Combustivel": "Gasolina",
            "CodigoFipe": "001004-9",
            "MesReferencia": "agosto de 2026",
        }

    client.get_price.side_effect = price_side_effect

    progress_msgs = []
    rows = crawl_latest_fipe_prices(client, on_progress=progress_msgs.append)

    assert len(rows) == 1
    assert any("boom" in msg for msg in progress_msgs)
