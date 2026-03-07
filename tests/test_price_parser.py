from decimal import Decimal

from app.common.price_parser import parse_price_decimal, parse_price_int_reais
from app.sources.normalize import normalize_ad


def test_parse_price_required_formats_to_decimal():
    cases = {
        "189.990": Decimal("189990"),
        "189.990,00": Decimal("189990.00"),
        "R$ 189.990": Decimal("189990"),
        "R$ 189.990,00": Decimal("189990.00"),
        "189990": Decimal("189990"),
        "189990.00": Decimal("189990.00"),
    }

    for raw, expected in cases.items():
        assert parse_price_decimal(raw) == expected


def test_parse_price_required_formats_to_int_reais():
    cases = [
        "189.990",
        "189.990,00",
        "R$ 189.990",
        "R$ 189.990,00",
        "189990",
        "189990.00",
    ]
    for raw in cases:
        assert parse_price_int_reais(raw) == 189990


def test_parse_price_empty_or_null_returns_none():
    assert parse_price_int_reais(None) is None
    assert parse_price_int_reais("") is None
    assert parse_price_int_reais("   ") is None


def test_parse_price_invalid_is_rejected():
    assert parse_price_int_reais("preço a combinar") is None
    assert parse_price_int_reais("R$ --") is None


def test_parse_price_non_zero_centavos_is_rejected_in_int_pipeline():
    assert parse_price_decimal("189990,50") == Decimal("189990.50")
    assert parse_price_int_reais("189990,50") is None


def test_normalize_ad_does_not_multiply_by_100_for_dot_decimal_format():
    ad = normalize_ad(
        "olx",
        {
            "external_id": "olx-1",
            "url": "https://example.com/a",
            "price": "189990.00",
        },
    )

    assert ad.price == 189990
