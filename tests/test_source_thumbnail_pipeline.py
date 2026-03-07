from app.services.source_execution_service import _ad_to_listing
from app.sources.ad_quality import enforce_ad_contract
from app.sources.normalize import normalize_ad


def test_normalization_to_listing_keeps_thumbnail_for_persistence_mapping():
    ad = normalize_ad(
        "olx",
        {
            "external_id": "abc",
            "url": "https://example.com/car/1",
            "title": "Car",
            "price": 10000,
            "location": "São Paulo - SP",
            "images": ["https://img.example/1.jpg", "https://img.example/2.jpg"],
        },
    )
    validated = enforce_ad_contract(ad).ad

    listing = _ad_to_listing(validated)

    assert listing["thumbnail_url"] == "https://img.example/1.jpg"
    assert listing["extras"].get("thumbnail_url") == "https://img.example/1.jpg"
