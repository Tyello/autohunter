"""
Testes para MercadoLivreScraper.
"""

import pytest
import json
from decimal import Decimal
from app.scrapers.sources.mercadolivre import MercadoLivreScraper
from app.sources.types import ScrapeContext
from app.scrapers.base import FetchBlocked


@pytest.fixture
def scraper():
    return MercadoLivreScraper()


@pytest.fixture
def ctx():
    return ScrapeContext(
        source="mercadolivre",
        browser_fallback_enabled=True,
    )


def test_build_search_url(scraper):
    """Testa construção de URL."""
    url = scraper.build_search_url("civic si")
    
    assert url == "https://lista.mercadolivre.com.br/veiculos/carros-caminhonetes/civic-si"
    assert "api.mercadolibre.com" not in url


def test_build_api_search_url_compat(scraper):
    url = scraper.build_api_search_url("civic si")
    assert "api.mercadolibre.com" in url


def test_is_vehicle_listing(scraper):
    """Testa detecção de anúncios de veículos."""
    # Veículo
    assert scraper._is_vehicle_listing(
        "https://carro.mercadolivre.com.br/MLB-123"
    ) is True
    
    # Produto (não veículo)
    assert scraper._is_vehicle_listing(
        "https://produto.mercadolivre.com.br/MLB-456"
    ) is False
    
    assert scraper._is_vehicle_listing(
        "https://www.mercadolivre.com.br/p/MLB789"
    ) is False


def test_is_tracking_url(scraper):
    """Testa detecção de URLs de tracking."""
    # Tracking
    assert scraper._is_tracking_url(
        "https://click.mercadolivre.com.br/brand_ads/clicks/123"
    ) is True
    
    # Normal
    assert scraper._is_tracking_url(
        "https://carro.mercadolivre.com.br/MLB-123"
    ) is False


def test_clean_url(scraper):
    """Testa limpeza de URL (remove query/fragment)."""
    url = "https://example.com/item/123?param=value#section"
    clean = scraper._clean_url(url)
    
    assert clean == "https://example.com/item/123"
    assert "?" not in clean
    assert "#" not in clean


def test_extract_attribute(scraper):
    """Testa extração de atributo da lista."""
    attributes = [
        {"id": "VEHICLE_YEAR", "value_name": "2019"},
        {"id": "KILOMETERS", "value_name": "50000"},
        {"id": "BRAND", "value_name": "Honda"},
    ]
    
    assert scraper._extract_attribute(attributes, "VEHICLE_YEAR") == "2019"
    assert scraper._extract_attribute(attributes, "KILOMETERS") == "50000"
    assert scraper._extract_attribute(attributes, "BRAND") == "Honda"
    assert scraper._extract_attribute(attributes, "NOT_EXISTS") is None


def test_parse_year(scraper):
    """Testa parsing de ano."""
    assert scraper._parse_year("2019") == 2019
    assert scraper._parse_year(2019) == 2019
    assert scraper._parse_year("abc") is None
    assert scraper._parse_year(1899) is None  # fora do range


def test_parse_km(scraper):
    """Testa parsing de km."""
    assert scraper._parse_km("50000") == 50000
    assert scraper._parse_km("50.000") == 50000
    assert scraper._parse_km("") is None


def test_normalize_fuel(scraper):
    """Testa normalização de combustível."""
    assert scraper._normalize_fuel("Flex") == "flex"
    assert scraper._normalize_fuel("Nafta") == "gasoline"
    assert scraper._normalize_fuel("Diesel") == "diesel"
    assert scraper._normalize_fuel("Elétrico") == "electric"
    assert scraper._normalize_fuel("") is None


def test_normalize_transmission(scraper):
    """Testa normalização de transmissão."""
    assert scraper._normalize_transmission("Manual") == "manual"
    assert scraper._normalize_transmission("Automática") == "automatic"
    assert scraper._normalize_transmission("CVT") == "automatic"
    assert scraper._normalize_transmission("") is None


def test_extract_raw_data_valid_json(scraper, ctx):
    """Testa extração de dados de JSON válido."""
    api_response = {
        "results": [
            {
                "id": "MLB123",
                "title": "Honda Civic",
                "price": 50000,
                "permalink": "https://carro.mercadolivre.com.br/MLB-123",
            },
            {
                "id": "MLB456",
                "title": "Peça de carro",  # produto
                "permalink": "https://produto.mercadolivre.com.br/MLB-456",
            },
        ]
    }
    
    raw_content = json.dumps(api_response)
    items = scraper.extract_raw_data(raw_content, ctx)
    
    # Deve filtrar apenas veículos
    assert len(items) == 1
    assert items[0]["id"] == "MLB123"


def test_extract_raw_data_html_returns_items(scraper, ctx):
    """Testa regressão: HTML com card válido deve retornar item."""
    html = """
    <html>
    <body>
      <li class="ui-search-layout__item">
        <a class="ui-search-link" href="https://carro.mercadolivre.com.br/MLB-123456789-honda-civic-si-_JM">
          <h2>Honda Civic Si 2.4 2015</h2>
        </a>
        <span class="price-tag-fraction">120.000</span>
        <span class="ui-search-item__location">São Paulo, SP</span>
        <span class="ui-search-item__attribute">2015</span>
        <span class="ui-search-item__attribute">80.000 km</span>
        <img src="https://example.com/civic.jpg" />
      </li>
    </body>
    </html>
    """

    items = scraper.extract_raw_data(html, ctx)

    assert len(items) == 1
    assert items[0]["id"] == "MLB123456789"
    assert "Honda Civic" in items[0]["title"]
    assert items[0]["url"].startswith("https://carro.mercadolivre.com.br/MLB-123456789")
    assert items[0]["price"] == "120.000"
    assert items[0]["location"] == "São Paulo, SP"
    assert items[0]["thumbnail"] == "https://example.com/civic.jpg"
    assert "2015" in items[0]["attributes"]
    assert "80.000 km" in items[0]["attributes"]


def test_extract_raw_data_json_non_vehicle_filtered(scraper, ctx):
    """Testa que JSON com URL não-veículo continua filtrado."""
    api_response = {
        "results": [
            {
                "id": "MLB999",
                "title": "Honda Civic Si",
                "permalink": "https://carro.mercadolivre.com.br/MLB-999-honda-civic-si-_JM",
                "price": 120000,
            },
            {
                "id": "MLB000",
                "title": "Produto não veículo",
                "permalink": "https://produto.mercadolivre.com.br/MLB-000-peca-_JM",
                "price": 100,
            },
        ]
    }

    items = scraper.extract_raw_data(json.dumps(api_response), ctx)

    assert len(items) == 1
    assert items[0]["id"] == "MLB999"
    assert items[0]["url"] == "https://carro.mercadolivre.com.br/MLB-999-honda-civic-si-_JM"


def test_extract_raw_data_html_non_vehicle_filtered(scraper, ctx):
    """Testa que HTML com URL não-veículo continua filtrado."""
    html = """
    <html>
    <body>
      <li class="ui-search-layout__item">
        <a class="ui-search-link" href="https://produto.mercadolivre.com.br/MLB-123456789-peca-_JM">
          <h2>Peça avulsa</h2>
        </a>
      </li>
    </body>
    </html>
    """

    items = scraper.extract_raw_data(html, ctx)

    assert items == []


def test_extract_raw_data_invalid_json(scraper, ctx):
    """Testa com JSON inválido (retorna vazio para fallback)."""
    raw_content = "<!DOCTYPE html><html>..."  # HTML
    
    items = scraper.extract_raw_data(raw_content, ctx)
    
    assert items == []


def test_parse_listing_valid(scraper):
    """Testa parsing de listing válido."""
    raw = {
        "id": "MLB123456",
        "title": "Honda Civic SI 2019",
        "price": 85000,
        "currency_id": "BRL",
        "permalink": "https://carro.mercadolivre.com.br/MLB-123456?param=value",
        "thumbnail": "http://http2.mlstatic.com/car.jpg",
        "location": {
            "city": {"name": "São Paulo"},
            "state": {"name": "SP"},
        },
        "attributes": [
            {"id": "VEHICLE_YEAR", "value_name": "2019"},
            {"id": "KILOMETERS", "value_name": "30000"},
            {"id": "BRAND", "value_name": "Honda"},
            {"id": "MODEL", "value_name": "Civic"},
            {"id": "FUEL_TYPE", "value_name": "Flex"},
            {"id": "TRANSMISSION", "value_name": "Manual"},
        ],
        "seller": {"id": 12345},
        "condition": "used",
    }
    
    parsed = scraper.parse_listing(raw)
    
    assert parsed is not None
    assert parsed["external_id"] == "MLB123456"
    assert parsed["title"] == "Honda Civic SI 2019"
    assert parsed["url"] == "https://carro.mercadolivre.com.br/MLB-123456"  # limpo
    assert "param" not in parsed["url"]  # query removida
    assert parsed["thumbnail_url"].startswith("https://")  # convertido
    assert parsed["price"] == Decimal("85000")
    assert parsed["currency"] == "BRL"
    assert parsed["location"] == "São Paulo, SP"
    assert parsed["year"] == 2019
    assert parsed["mileage_km"] == 30000
    assert parsed["make"] == "Honda"
    assert parsed["model"] == "Civic"
    assert parsed["fuel_type"] == "flex"
    assert parsed["transmission"] == "manual"
    assert parsed["extractor_version"] == "mercadolivre_v1"
    assert parsed["extras"]["seller_id"] == 12345


def test_parse_listing_minimal(scraper):
    """Testa parsing com campos mínimos."""
    raw = {
        "id": "MLB999",
        "permalink": "https://carro.mercadolivre.com.br/MLB-999",
        "title": "Carro usado",
    }
    
    parsed = scraper.parse_listing(raw)
    
    assert parsed is not None
    assert parsed["external_id"] == "MLB999"
    assert parsed["title"] == "Carro usado"
    assert parsed["price"] is None
    assert parsed["year"] is None


def test_parse_listing_invalid_no_id(scraper):
    """Testa que retorna None sem ID."""
    raw = {
        "title": "Carro",
        "permalink": "https://example.com",
    }
    
    assert scraper.parse_listing(raw) is None


def test_parse_listing_invalid_no_url(scraper):
    """Testa que retorna None sem URL."""
    raw = {
        "id": "MLB123",
        "title": "Carro",
    }
    
    assert scraper.parse_listing(raw) is None


def test_parse_listing_tracking_url_filtered(scraper):
    """Testa que tracking URLs são filtradas."""
    raw = {
        "id": "MLB123",
        "title": "Carro",
        "permalink": "https://click.mercadolivre.com.br/brand_ads/clicks/123",
    }
    
    # Deve retornar None (filtrado)
    assert scraper.parse_listing(raw) is None


def test_parse_listing_attributes_string_defensive(scraper):
    raw = {
        "id": "MLB777",
        "title": "Honda Civic SI 2015",
        "url": "https://carro.mercadolivre.com.br/MLB-777-honda-civic-si-_JM",
        "price": "120.000",
        "attributes": ["2015", "80.000 km"],
        "thumbnail": "https://img.example/civic.jpg",
    }
    parsed = scraper.parse_listing(raw)
    assert parsed is not None
    assert parsed["year"] == 2015
    assert parsed["mileage_km"] == 80000


def test_fetch_content_uses_ml_helper(monkeypatch, scraper, ctx):
    called = {"count": 0}

    def _fake_fetch(url, _ctx):
        called["count"] += 1
        return "<html><li class='ui-search-layout__item'></li></html>"

    monkeypatch.setattr("app.scrapers.sources.mercadolivre._fetch_ml_search_with_shell_fallback", _fake_fetch)
    res = scraper._fetch_content(scraper.build_search_url("civic si"), ctx)
    assert called["count"] == 1
    assert "ui-search-layout__item" in res.content


def test_fetch_content_shell_raises_blocked(monkeypatch, scraper, ctx):
    monkeypatch.setattr("app.scrapers.sources.mercadolivre._fetch_ml_search_with_shell_fallback", lambda *_: "<html><title>Mercado Livre Brasil</title></html>")
    with pytest.raises(FetchBlocked):
        scraper._fetch_content(scraper.build_search_url("civic si"), ctx)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
