from __future__ import annotations

import json
from decimal import Decimal

from app.scrapers.mercadolivre import (
    _extract_external_id_from_url,
    _extract_price_from_vip_html,
    _normalize_ml_url,
)
from app.scrapers.olx import _extract_next_data_json
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
