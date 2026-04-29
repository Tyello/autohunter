from __future__ import annotations

from decimal import Decimal

from app.models.car_listing import CarListing
from app.schemas.car_listing import CarListingOut


def test_car_listing_out_from_orm(db):
    listing = CarListing(
        source="mercadolivre",
        external_id="MLB123",
        title="Daihatsu Cuore 1996",
        url="https://carro.mercadolivre.com.br/MLB-123-_JM",
        thumbnail_url="https://img.example.com/1.jpg",
        price=Decimal("459.00"),
        currency="BRL",
        location="SP",
    )

    db.add(listing)
    db.commit()
    db.refresh(listing)

    out = CarListingOut.model_validate(listing)

    assert str(out.id) == str(listing.id)
    assert out.source == "mercadolivre"
    assert out.listing_url == listing.url
    assert out.thumbnail_url == listing.thumbnail_url
    assert out.price == 459.0
    assert out.currency == "BRL"
    assert out.created_at == listing.created_at


def test_car_listing_out_accepts_url_payload_alias():
    out = CarListingOut.model_validate({
        "id": "11111111-1111-1111-1111-111111111111",
        "source": "olx",
        "title": "Car",
        "price": 10,
        "currency": "BRL",
        "thumbnail_url": None,
        "url": "https://example.com/url",
        "location": "SP",
        "created_at": "2026-04-29T00:00:00Z",
    })
    assert out.listing_url == "https://example.com/url"


def test_car_listing_out_accepts_legacy_listing_url_payload():
    out = CarListingOut.model_validate({
        "id": "22222222-2222-2222-2222-222222222222",
        "source": "olx",
        "title": "Car",
        "price": 10,
        "currency": "BRL",
        "thumbnail_url": None,
        "listing_url": "https://example.com/legacy",
        "location": "SP",
        "created_at": "2026-04-29T00:00:00Z",
    })
    assert out.listing_url == "https://example.com/legacy"
