from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

from app.models.car_listing import CarListing
from app.models.user import User
from app.models.wishlist import Wishlist
from app.services.matching_service import match_listings_for_active_wishlists


def test_match_listings_for_active_wishlists_uses_bool_match_result(db, monkeypatch):
    user = User(id=uuid.uuid4(), telegram_chat_id=5511999999999, username="active-test", is_active=True)
    db.add(user)
    db.commit()

    wishlist = Wishlist(user_id=user.id, query="civic si", is_active=True)
    db.add(wishlist)
    db.commit()

    listing = CarListing(
        source="olx",
        external_id="olx-123",
        title="Honda Civic Hatch SI 1994",
        url="https://www.olx.com.br/autos-e-pecas/carro/civic-si-123",
        price=Decimal("45000"),
        currency="BRL",
        location="Curitiba, PR",
    )

    def _fake_candidates(_db, listing_id_to_text):
        assert listing.id in listing_id_to_text
        return (
            {listing.id: [wishlist.id]},
            SimpleNamespace(
                candidates_p50=1,
                candidates_p95=1,
                wishlists_loaded=1,
                listings=1,
                unique_tokens=2,
            ),
        )

    monkeypatch.setattr(
        "app.services.wishlist_tokens_service.candidate_wishlist_ids_for_listings",
        _fake_candidates,
    )

    out, stats = match_listings_for_active_wishlists(db, [listing])

    assert wishlist.id in out
    assert out[wishlist.id] == [listing]
    assert stats["candidate_wishlists"] == 1
