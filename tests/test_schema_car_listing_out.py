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
