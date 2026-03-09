from app.services.source_execution_service import _ad_to_listing
from app.sources.ad_quality import enforce_ad_contract
from app.sources.normalize import (
    normalize_ad,
    normalize_color,
    normalize_external_id,
    normalize_fuel_type,
    normalize_location,
    normalize_mileage_km,
    normalize_transmission,
    resolve_thumbnail_url,
    split_make_model_version,
)


def test_external_id_never_from_price_and_has_hash_fallback():
    eid = normalize_external_id(source="olx", raw_external_id="123456", url="https://x/1", title="Car", price="123.456")
    assert eid != "123456"
    assert len(eid or "") == 16


def test_location_city_state_normalization():
    location, city, state = normalize_location("em São Paulo, SP")
    assert location == "São Paulo-SP"
    assert city == "São Paulo"
    assert state == "SP"

    _, city2, state2 = normalize_location("Sorocaba, São Paulo")
    assert city2 == "Sorocaba"
    assert state2 == "SP"


def test_mileage_normalization_variants():
    assert normalize_mileage_km("123.456") == 123456
    assert normalize_mileage_km("123456") == 123456
    assert normalize_mileage_km("123.456 km") == 123456


def test_fuel_and_transmission_normalization():
    assert normalize_fuel_type("gasolina") == "Gasolina"
    assert normalize_fuel_type("hibrido") == "Híbrido"
    assert normalize_transmission("Câmbio Automático") == "Automática"
    assert normalize_transmission("manual") == "Manual"


def test_thumbnail_resolution_and_make_model_version_split():
    assert resolve_thumbnail_url(None, ["https://img/1.jpg"]) == "https://img/1.jpg"
    assert resolve_thumbnail_url("https://img/cover.jpg", ["https://img/1.jpg"]) == "https://img/cover.jpg"

    mk, md, ver = split_make_model_version(None, None, "Audi A5 Ambit. Plus Sport. 2.0 Tfsi S Tronic")
    assert (mk, md, ver) == ("Audi", "A5", "Ambit. Plus Sport. 2.0 Tfsi S Tronic")


def test_color_normalization():
    assert normalize_color("pRETo") == "Preto"


def test_persistence_contract_fields_are_mapped_and_not_empty():
    ad = normalize_ad(
        "chavesnamao",
        {
            "url": "https://example.com/car/1",
            "title": "Honda Civic Sedan Si 2.0 16V 192cv 4p",
            "price": "R$ 95.000",
            "location": "em Campinas, SP",
            "mileage_km": "93.206",
            "fuel_type": "Flex",
            "transmission": "Automática",
            "color": "PRATA",
            "images": ["https://img.example/1.jpg"],
        },
    )
    validated = enforce_ad_contract(ad).ad
    listing = _ad_to_listing(validated)

    assert listing["version"] == "Sedan Si 2.0 16V 192cv 4p"
    assert listing["seller_type"] == "unknown"
    assert listing["city"] == "Campinas"
    assert listing["state"] == "SP"
    assert listing["color"] == "Prata"
    assert listing["raw_payload"]
    assert listing["extractor_version"]


def test_mobiauto_thumbnail_does_not_flag_missing_images_with_explicit_thumb():
    ad = normalize_ad(
        "mobiauto",
        {
            "external_id": "m1",
            "url": "https://example.com/m1",
            "title": "Car",
            "price": 10000,
            "thumbnail_url": "https://img.example/cover.jpg",
            "images": [],
        },
    )
    validated = enforce_ad_contract(ad)
    assert "missing_images" not in validated.quality_flags


def test_chavesnamao_style_price_external_id_is_replaced():
    ad = normalize_ad(
        "chavesnamao",
        {
            "external_id": "90000",
            "url": "https://example.com/chv/abc",
            "title": "Car",
            "price": "90000",
        },
    )
    assert ad.external_id != "90000"
