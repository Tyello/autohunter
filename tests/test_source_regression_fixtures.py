from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from app.sources.types import ScrapeContext
from app.scrapers.icarros import scrape_icarros
from app.scrapers.mercadolivre import scrape_mercadolivre
from tests.helpers.source_regression import (
    assert_core_fields,
    assert_optional_absent,
    index_by_external_id,
    load_expectations,
    load_fixture,
)


def test_icarros_listing_and_detail_regression_with_realistic_fixtures(monkeypatch):
    source = "icarros"
    scenario = "basic_realistic"
    listing_html = load_fixture(source, scenario, "listing.html")
    detail_1 = load_fixture(source, scenario, "detail_52934717.html")
    detail_2 = load_fixture(source, scenario, "detail_52934718.html")
    expectations = load_expectations(source, scenario)

    def _fake_fetch(url: str, **kwargs):
        if "d52934717" in url:
            return SimpleNamespace(html=detail_1, final_url=url)
        if "d52934718" in url:
            return SimpleNamespace(html=detail_2, final_url=url)
        return SimpleNamespace(html=listing_html, final_url=url)

    monkeypatch.setattr("app.scrapers.icarros.fetch_html_browser", _fake_fetch)

    ctx = ScrapeContext(source="icarros")
    items = scrape_icarros("https://www.icarros.com.br/comprar/usados/honda/civic", ctx)
    indexed = index_by_external_id(items)

    assert len(indexed) == 2

    for ext_id, cfg in expectations["records"].items():
        item = indexed[ext_id]
        assert_core_fields(item, expectations["required_fields"])
        assert_core_fields(item, cfg.get("must_have", []))
        assert_optional_absent(item, cfg.get("optional_absent", []))

        assert int(item["price"]) == cfg["expected"]["price"]
        if "location" in cfg["expected"]:
            assert item.get("location") == cfg["expected"]["location"]
        for token in cfg["expected"]["title_contains"]:
            assert token in (item.get("title") or "")


def test_mercadolivre_listing_and_detail_price_regression_with_realistic_fixtures(monkeypatch):
    source = "mercadolivre"
    scenario = "basic_realistic"
    listing_html = load_fixture(source, scenario, "listing.html")
    detail_html = load_fixture(source, scenario, "detail_MLB6177621992.html")
    expectations = load_expectations(source, scenario)

    def _fake_fetch(url: str, ctx=None, timeout=25):
        if "MLB-6177621992" in url:
            return detail_html
        return listing_html

    monkeypatch.setattr("app.scrapers.mercadolivre._fetch_html_ml", _fake_fetch)

    ctx = ScrapeContext(source="mercadolivre", browser_fallback_enabled=False)
    items = scrape_mercadolivre("https://lista.mercadolivre.com.br/honda-civic", ctx)
    indexed = index_by_external_id(items)

    assert len(indexed) >= 2

    for ext_id, cfg in expectations["records"].items():
        item = indexed[ext_id]
        assert_core_fields(item, expectations["required_fields"])
        assert_core_fields(item, cfg.get("must_have", []))
        assert_optional_absent(item, cfg.get("optional_absent", []))

        assert int(Decimal(str(item["price"]))) == cfg["expected"]["price"]
        if "location" in cfg["expected"]:
            assert item.get("location") == cfg["expected"]["location"]
        for token in cfg["expected"]["title_contains"]:
            assert token in (item.get("title") or "")
