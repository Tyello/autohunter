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

    rows = crawl_latest_fipe_prices(client_factory=lambda: client)

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

    crawl_latest_fipe_prices(client_factory=lambda: client, limit_brands=2)

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
    rows = crawl_latest_fipe_prices(client_factory=lambda: client, on_progress=progress_msgs.append)

    assert len(rows) == 1
    assert any("boom" in msg for msg in progress_msgs)


def _multi_brand_client(n_brands=4):
    client = Mock(spec=FipeApiClient)
    client.get_latest_reference_table.return_value = {"Codigo": 320, "Mes": "agosto/2026"}
    client.get_brands.return_value = [{"Value": str(i), "Label": f"Brand{i}"} for i in range(n_brands)]
    client.get_models.return_value = [{"Value": "100", "Label": "ModelA"}]
    client.get_model_years.return_value = [{"Value": "2020-1", "Label": "2020"}]
    client.get_price.return_value = {
        "Valor": "R$ 50.000,00",
        "Marca": "MarcaX",
        "Modelo": "ModelA",
        "AnoModelo": 2020,
        "Combustivel": "Gasolina",
        "CodigoFipe": "000000-0",
        "MesReferencia": "agosto de 2026",
    }
    return client


def test_crawl_uses_client_factory_and_concurrency():
    client = _multi_brand_client(n_brands=4)
    factory_calls = {"n": 0}

    def factory():
        factory_calls["n"] += 1
        return client

    rows_concurrent = crawl_latest_fipe_prices(client_factory=factory, concurrency=3)
    rows_sequential = crawl_latest_fipe_prices(client_factory=lambda: client, concurrency=1)

    assert factory_calls["n"] >= 1
    assert len(rows_concurrent) == 4
    assert {r["marca"] for r in rows_concurrent} == {r["marca"] for r in rows_sequential}
    assert len(rows_concurrent) == len(rows_sequential)


def test_individual_task_error_does_not_abort_crawl():
    client = _multi_brand_client(n_brands=3)

    def price_side_effect(**kwargs):
        if kwargs["brand_code"] == "1":
            raise RuntimeError("unexpected failure")
        return {
            "Valor": "R$ 50.000,00",
            "Marca": "MarcaX",
            "Modelo": "ModelA",
            "AnoModelo": 2020,
            "Combustivel": "Gasolina",
            "CodigoFipe": "000000-0",
            "MesReferencia": "agosto de 2026",
        }

    client.get_price.side_effect = price_side_effect

    rows = crawl_latest_fipe_prices(client_factory=lambda: client, concurrency=3)

    assert len(rows) == 2


def test_progress_logging_reports_throughput_and_eta(monkeypatch):
    monkeypatch.setattr("app.core.settings.settings.fipe_crawler_progress_log_every", 2)
    client = _multi_brand_client(n_brands=5)

    progress_msgs = []
    crawl_latest_fipe_prices(client_factory=lambda: client, concurrency=2, on_progress=progress_msgs.append)

    assert any("ETA" in msg for msg in progress_msgs)
