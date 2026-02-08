"""
Testes para ICarrosScraper.
"""

import pytest
from decimal import Decimal
from app.scrapers.sources.icarros import ICarrosScraper
from app.sources.types import ScrapeContext


@pytest.fixture
def scraper():
    return ICarrosScraper()


@pytest.fixture
def ctx():
    return ScrapeContext(
        source="icarros",
        http_timeout_s=20,
    )


def test_build_search_url(scraper):
    """Testa construção de URL."""
    url = scraper.build_search_url("civic si")
    
    assert "icarros.com.br" in url
    assert "civic+si" in url or "civic%20si" in url
    assert "saopaulo" in url  # default location


def test_build_search_url_custom_location(scraper):
    """Testa URL com localização customizada."""
    url = scraper.build_search_url("civic", location="riodejaneiro")
    
    assert "riodejaneiro" in url


def test_parse_price(scraper):
    """Testa parsing de preços."""
    assert scraper._parse_price("R$ 50.000") == Decimal("50000")
    assert scraper._parse_price("R$ 50.000,00") == Decimal("50000")
    assert scraper._parse_price("50000") == Decimal("50000")
    assert scraper._parse_price("") is None
    assert scraper._parse_price("abc") is None


def test_parse_year(scraper):
    """Testa parsing de ano."""
    assert scraper._parse_year("2019") == 2019
    assert scraper._parse_year("2019/2020") == 2019  # pega primeiro
    assert scraper._parse_year("") is None
    assert scraper._parse_year("abc") is None
    assert scraper._parse_year("1899") is None  # fora do range


def test_parse_km(scraper):
    """Testa parsing de quilometragem."""
    assert scraper._parse_km("50.000 km") == 50000
    assert scraper._parse_km("50000km") == 50000
    assert scraper._parse_km("50 mil km") == 50000
    assert scraper._parse_km("50,5 mil km") == 50500
    assert scraper._parse_km("") is None


def test_extract_make_model(scraper):
    """Testa extração de marca e modelo."""
    make, model = scraper._extract_make_model("Honda Civic SI 2019")
    assert make == "Honda"
    assert model == "Civic"
    
    make, model = scraper._extract_make_model("Volkswagen Gol 1.0")
    assert make == "Volkswagen"
    assert model == "Gol"
    
    make, model = scraper._extract_make_model("VW Golf GTI")
    assert make == "Volkswagen"  # normaliza VW
    assert model == "Golf"


def test_normalize_transmission(scraper):
    """Testa normalização de transmissão."""
    assert scraper._normalize_transmission("Manual") == "manual"
    assert scraper._normalize_transmission("Mecânica") == "manual"
    assert scraper._normalize_transmission("Automática") == "automatic"
    assert scraper._normalize_transmission("CVT") == "automatic"
    assert scraper._normalize_transmission("") is None


def test_normalize_fuel(scraper):
    """Testa normalização de combustível."""
    assert scraper._normalize_fuel("Flex") == "flex"
    assert scraper._normalize_fuel("Gasolina") == "gasoline"
    assert scraper._normalize_fuel("Etanol") == "ethanol"
    assert scraper._normalize_fuel("Diesel") == "diesel"
    assert scraper._normalize_fuel("Elétrico") == "electric"
    assert scraper._normalize_fuel("Híbrido") == "hybrid"
    assert scraper._normalize_fuel("") is None


def test_parse_listing_valid(scraper):
    """Testa parsing de listing válido."""
    raw = {
        "url": "https://www.icarros.com.br/anuncio/123456",
        "title": "Honda Civic SI 2019",
        "price": "R$ 85.000",
        "location": "São Paulo, SP",
        "thumbnail": "/images/car.jpg",
        "mileage": "30.000 km",
        "year": "2019",
        "transmission": "Manual",
        "fuel": "Flex",
    }
    
    parsed = scraper.parse_listing(raw)
    
    assert parsed is not None
    assert parsed["external_id"] == "123456"
    assert parsed["title"] == "Honda Civic SI 2019"
    assert parsed["url"] == "https://www.icarros.com.br/anuncio/123456"
    assert parsed["price"] == Decimal("85000")
    assert parsed["year"] == 2019
    assert parsed["mileage_km"] == 30000
    assert parsed["make"] == "Honda"
    assert parsed["model"] == "Civic"
    assert parsed["transmission"] == "manual"
    assert parsed["fuel_type"] == "flex"
    assert parsed["extractor_version"] == "icarros_v1"


def test_parse_listing_minimal(scraper):
    """Testa parsing com campos mínimos."""
    raw = {
        "url": "https://www.icarros.com.br/anuncio/999",
        "title": "Carro usado",
    }
    
    parsed = scraper.parse_listing(raw)
    
    assert parsed is not None
    assert parsed["external_id"] == "999"
    assert parsed["title"] == "Carro usado"
    assert parsed["price"] is None
    assert parsed["year"] is None


def test_parse_listing_invalid_no_url(scraper):
    """Testa que retorna None sem URL."""
    raw = {
        "title": "Carro",
    }
    
    assert scraper.parse_listing(raw) is None


def test_extract_id_from_url(scraper):
    """Testa extração de ID do URL."""
    assert scraper._extract_id_from_url(
        "https://www.icarros.com.br/anuncio/123456"
    ) == "123456"
    
    assert scraper._extract_id_from_url(
        "https://www.icarros.com.br/anuncios/honda-civic/789"
    ) == "789"
    
    # Fallback para hash
    id_hash = scraper._extract_id_from_url("https://example.com/unknown")
    assert id_hash is not None
    assert len(id_hash) == 16  # MD5 truncado


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
