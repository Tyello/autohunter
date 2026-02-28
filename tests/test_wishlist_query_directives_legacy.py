from __future__ import annotations

import uuid
from decimal import Decimal

from app.models.car_listing import CarListing
from app.models.user import User
from app.models.wishlist import Wishlist
from app.services.matching_service import explain_match, match_listing_to_wishlist


def _mk_user(db) -> User:
    u = User(id=uuid.uuid4(), telegram_chat_id=5410199985, username="test", is_active=True)
    db.add(u)
    db.commit()
    return u


def test_legacy_query_with_year_range_is_parsed_into_filters(db):
    """Wishlists antigas podem ter diretivas no texto.

    Mesmo sem rows em wishlist_filters, o matcher deve:
      - limpar os termos ("entre 2014 e 2020")
      - aplicar o range de ano como filtro inclusivo
    """
    u = _mk_user(db)
    w = Wishlist(user_id=u.id, query="audi a6 entre 2014 e 2020", is_active=True)
    db.add(w)
    db.commit()
    db.refresh(w)

    ok = CarListing(
        source="olx",
        external_id="1",
        title="Audi A6 2016 2.0 TFSI",
        url="https://www.olx.com.br/1",
        price=Decimal("90000"),
        currency="BRL",
    )

    old = CarListing(
        source="olx",
        external_id="2",
        title="Audi A6 2012 2.0 TFSI",
        url="https://www.olx.com.br/2",
        price=Decimal("80000"),
        currency="BRL",
    )

    assert match_listing_to_wishlist(db, w, ok) is True
    assert explain_match(w, ok) == "ok"

    assert match_listing_to_wishlist(db, w, old) is False
    # The failure should be year comparison, not text_terms.
    assert explain_match(w, old).startswith("filter_year")
