from __future__ import annotations

import json
from decimal import Decimal

from app.scrapers.mercadolivre import (
    _extract_external_id_from_url,
    _extract_price_from_vip_html,
    _normalize_ml_url,
)
from app.scrapers.olx import _extract_next_data_json, OlxItem, _items_to_dicts
from app.scrapers.parsing import parse_brl_price


def test_parse_brl_price_common_formats():
    assert parse_brl_price("R$ 85.900") == Decimal("85900")
    assert parse_brl_price("85.900") == Decimal("85900")
    assert parse_brl_price("1.234.567,89") == Decimal("1234567.89")


def test_mercadolivre_extract_external_id_from_url():
    url = "https://carro.mercadolivre.com.br/MLB-6160123242-honda-civic-hatch-si-1994-_JM"
    assert _extract_external_id_from_url(url) == "MLB6160123242"


def test_mercadolivre_normalizes_tracking_url_to_canonical_when_id_known():
    tracking = "https://click1.mercadolivre.com.br/brand_ads/clicks/external?something=1"
    out = _normalize_ml_url(tracking, external_id="MLB6160123242")
    assert out == "https://carro.mercadolivre.com.br/MLB-6160123242-_JM"


def test_mercadolivre_extract_price_from_preloaded_state():
    state = {
        "pageState": {
            "initialState": {
                "components": {
                    "short_description": [
                        {"id": "price", "type": "price", "price": {"value": 165590}}
                    ]
                }
            }
        }
    }
    html = f"""
    <html><head></head><body>
      <script id=\"__PRELOADED_STATE__\" type=\"application/json\">{json.dumps(state)}</script>
    </body></html>
    """
    assert _extract_price_from_vip_html(html) == 165590


def test_olx_extracts_next_data_json():
    payload = {"props": {"pageProps": {"ads": []}}}
    html = f"""
    <html><body>
      <script id=\"__NEXT_DATA__\" type=\"application/json\">{json.dumps(payload)}</script>
    </body></html>
    """
    assert _extract_next_data_json(html) == payload


def test_olx_extracts_year_and_mileage_from_title():
    item = OlxItem(
        external_id="12345",
        title="Honda Fit 2007 1.4 Flex 45.000 km",
        url="https://olx.com.br/item/12345",
        thumbnail_url=None,
        price=Decimal("25000"),
        currency="BRL",
        location="São Paulo, SP",
    )
    result = _items_to_dicts([item])
    assert len(result) == 1
    d = result[0]
    assert d["year"] == 2007
    assert d["km"] == 45000


def test_olx_missing_year_or_mileage_returns_none():
    # Case 1: missing km, has year
    item1 = OlxItem(
        external_id="12346",
        title="Honda Fit 2007 1.4 Flex",
        url="https://olx.com.br/item/12346",
        thumbnail_url=None,
        price=Decimal("25000"),
        currency="BRL",
        location="São Paulo, SP",
    )
    result1 = _items_to_dicts([item1])
    assert len(result1) == 1
    d1 = result1[0]
    assert d1.get("km") is None
    assert d1["year"] == 2007

    # Case 2: missing both year and km
    item2 = OlxItem(
        external_id="12347",
        title="Honda Fit Impecavel Revisado",
        url="https://olx.com.br/item/12347",
        thumbnail_url=None,
        price=Decimal("25000"),
        currency="BRL",
        location="São Paulo, SP",
    )
    result2 = _items_to_dicts([item2])
    assert len(result2) == 1
    d2 = result2[0]
    assert d2.get("year") is None
    assert d2.get("km") is None
