from __future__ import annotations

import uuid
from decimal import Decimal

from app.models.car_listing import CarListing
from app.models.user import User
from app.models.wishlist import Wishlist
from app.services.matching_service import match_listing_to_wishlist
from app.services.wishlist_semantic_rules import semantic_match


def _mk_user(db) -> User:
    u = User(id=uuid.uuid4(), telegram_chat_id=5410199985, username="test", is_active=True)
    db.add(u)
    db.commit()
    return u


def _mk_wishlist(db, user: User, query: str) -> Wishlist:
    w = Wishlist(user_id=user.id, query=query, is_active=True)
    db.add(w)
    db.commit()
    return w


def test_civic_si_matches_si_listing(db):
    u = _mk_user(db)
    w = _mk_wishlist(db, u, "civic si")

    listing = CarListing(
        source="olx",
        external_id="1",
        title="Honda Civic Hatch SI 1994",
        url="https://www.olx.com.br/1",
        price=Decimal("32000"),
        currency="BRL",
        location="Curitiba, PR",
    )

    assert semantic_match(w, listing) is True
    assert match_listing_to_wishlist(db, w, listing) is True


def test_civic_si_does_not_match_generic_civic(db):
    u = _mk_user(db)
    w = _mk_wishlist(db, u, "civic si")

    # Original false positive example: should NOT match without "si" token.
    listing = CarListing(
        source="mercadolivre",
        external_id="MLB-FAKE",
        title="Honda Civic 2015 2.0 LXR 16V",
        url="https://carro.mercadolivre.com.br/MLB-6177621992-_JM",
        price=Decimal("77990"),
        currency="BRL",
        location="São Paulo, SP",
    )

    assert semantic_match(w, listing) is False
    assert match_listing_to_wishlist(db, w, listing) is False


def test_civic_hatch_blocks_type_r(db):
    u = _mk_user(db)
    w = _mk_wishlist(db, u, "civic hatch")

    listing = CarListing(
        source="chavesnamao",
        external_id="8084877",
        title="Honda Civic 2.0 TYPE-R TURBO 16V 4P 2024",
        url="https://www.chavesnamao.com.br/carro/pr-curitiba/8084877/",
        price=Decimal("389990"),
        currency="BRL",
        location="Curitiba, PR",
    )

    assert semantic_match(w, listing) is False
    assert match_listing_to_wishlist(db, w, listing) is False


def test_matching_ignores_mercadolivre_tracking_url_noise(db):
    u = _mk_user(db)
    w = _mk_wishlist(db, u, "civic si")

    # Tracking URLs sometimes contain short tokens like "si" by coincidence.
    listing = CarListing(
        source="mercadolivre",
        external_id="MLB999999999",
        title="Honda Civic 2015 2.0 LXR 16V",
        url="https://click1.mercadolivre.com.br/brand_ads/clicks/external?foo=si&bar=baz",
        price=Decimal("77990"),
        currency="BRL",
    )

    assert match_listing_to_wishlist(db, w, listing) is False
