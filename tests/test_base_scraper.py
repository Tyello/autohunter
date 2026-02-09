"""
Testes para BaseScraper.
"""

import pytest
import time
from decimal import Decimal
from app.scrapers.scraper_base.scraper import BaseScraper, ScraperResult
from app.sources.types import ScrapeContext


class MockScraper(BaseScraper):
    """Scraper mock para testes."""
    
    def __init__(self):
        super().__init__(source_name="mock_source")
        self.mock_items = []
    
    def build_search_url(self, query: str, **kwargs) -> str:
        return f"https://mock.com/search?q={query}"
    
    def extract_raw_data(self, raw_content: str, ctx):
        # Retorna items mockados
        return self.mock_items
    
    def parse_listing(self, raw_data: dict):
        # Parse simples
        return {
            "external_id": raw_data.get("id"),
            "title": raw_data.get("title", ""),
            "url": raw_data.get("url"),
            "price": Decimal(str(raw_data.get("price", 0))),
        }


def test_base_scraper_build_search_url():
    """Teste do build_search_url."""
    scraper = MockScraper()
    url = scraper.build_search_url("civic si")
    
    assert url == "https://mock.com/search?q=civic si"


def test_base_scraper_parse_listing():
    """Teste do parse_listing."""
    scraper = MockScraper()
    
    raw = {
        "id": "123",
        "title": "Honda Civic SI",
        "url": "https://mock.com/item/123",
        "price": 50000
    }
    
    parsed = scraper.parse_listing(raw)
    
    assert parsed["external_id"] == "123"
    assert parsed["title"] == "Honda Civic SI"
    assert parsed["url"] == "https://mock.com/item/123"
    assert parsed["price"] == Decimal("50000")


def test_base_scraper_pipeline_success(monkeypatch):
    """Teste do pipeline completo (sucesso)."""
    scraper = MockScraper()
    scraper.mock_items = [
        {"id": "1", "title": "Car 1", "price": 10000, "url": "https://mock.com/item/1"},
        {"id": "2", "title": "Car 2", "price": 20000, "url": "https://mock.com/item/2"},
    ]
    
    # Mock unified_fetch para não fazer request real
    def mock_fetch(url, ctx, source):
        from app.scrapers.scraper_base.fetcher import FetchResult
        return FetchResult(
            content="mock_html",
            final_url=url,
            method="http",
            duration_ms=100
        )
    
    monkeypatch.setattr("app.scrapers.scraper_base.scraper.unified_fetch", mock_fetch)
    
    ctx = ScrapeContext(source="mock_source")
    result = scraper.scrape("https://mock.com/search", ctx)
    
    assert result.success is True
    assert len(result.listings) == 2
    assert result.metrics.items_valid == 2
    assert result.metrics.fetch_method == "http"
    assert result.blocked is False


def test_base_scraper_pipeline_invalid_items(monkeypatch):
    """Teste com items inválidos (missing fields)."""
    scraper = MockScraper()
    scraper.mock_items = [
        {"id": "1", "title": "Car 1"},  # sem URL
        {"title": "Car 2", "url": "http://x"},  # sem ID
        {"id": "3", "url": "http://y", "title": "Car 3"},  # OK
    ]
    
    def mock_fetch(url, ctx, source):
        from app.scrapers.scraper_base.fetcher import FetchResult
        return FetchResult(content="", final_url=url, method="http", duration_ms=100)
    
    monkeypatch.setattr("app.scrapers.scraper_base.scraper.unified_fetch", mock_fetch)
    
    ctx = ScrapeContext(source="mock_source")
    result = scraper.scrape("https://mock.com/search", ctx)
    
    # Apenas 1 item válido
    assert len(result.listings) == 1
    assert result.metrics.items_valid == 1
    assert result.metrics.items_invalid == 2
    assert len(result.warnings) >= 2


def test_base_scraper_source_injection(monkeypatch):
    """Teste que source é injetado automaticamente."""
    scraper = MockScraper()
    scraper.mock_items = [{"id": "1", "title": "Car", "url": "http://x"}]
    
    def mock_fetch(url, ctx, source):
        from app.scrapers.scraper_base.fetcher import FetchResult
        return FetchResult(content="", final_url=url, method="http", duration_ms=100)
    
    monkeypatch.setattr("app.scrapers.scraper_base.scraper.unified_fetch", mock_fetch)
    
    ctx = ScrapeContext(source="mock_source")
    result = scraper.scrape("https://mock.com/search", ctx)
    
    assert result.listings[0]["source"] == "mock_source"


def test_base_scraper_circuit_breaker_open(monkeypatch):
    """Teste que circuit breaker aberto pula scrape."""
    scraper = MockScraper()
    
    # Força circuit breaker aberto
    scraper._circuit_breaker._state.state = "open"
    scraper._circuit_breaker._state.opened_at = time.time()
    
    ctx = ScrapeContext(source="mock_source")
    result = scraper.scrape("https://mock.com/search", ctx)
    
    assert result.blocked is True
    assert len(result.listings) == 0
    assert result.metrics.circuit_breaker_state == "open"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
