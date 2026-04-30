from __future__ import annotations

import uuid
from decimal import Decimal

from app.models.car_listing import CarListing
from app.models.user import User
from app.models.wishlist import Wishlist
from app.models.wishlist_filter import WishlistFilter
from app.services.matching_service import explain_match, match_listing_to_wishlist


def _mk_wishlist(db, field: str, op: str, value: str) -> Wishlist:
    u = User(id=uuid.uuid4(), telegram_chat_id=5410199777 + (uuid.uuid4().int % 1000000), username=str(uuid.uuid4())[:8], is_active=True)
    db.add(u)
    db.commit()
    w = Wishlist(user_id=u.id, query="civic", is_active=True)
    db.add(w)
    db.commit()
    db.add(WishlistFilter(wishlist_id=w.id, field=field, operator=op, value=value))
    db.commit()
    db.refresh(w)
    return w


def _listing(seller_type):
    return CarListing(source="olx", external_id=str(uuid.uuid4()), title="Honda Civic 2019", url=f"https://olx.com/{uuid.uuid4()}", price=Decimal("45000"), currency="BRL", seller_type=seller_type)


def test_seller_type_eq_and_neq_matching(db):
    w_eq = _mk_wishlist(db, "seller_type", "eq", "private")
    assert match_listing_to_wishlist(db, w_eq, _listing("private")) is True
    assert match_listing_to_wishlist(db, w_eq, _listing("dealer")) is False
    assert explain_match(w_eq, _listing("dealer")) == "filter_seller_type_eq"

    w_neq = _mk_wishlist(db, "seller_type", "neq", "dealer")
    assert match_listing_to_wishlist(db, w_neq, _listing("private")) is True
    assert match_listing_to_wishlist(db, w_neq, _listing("dealer")) is False
    assert explain_match(w_neq, _listing("dealer")) == "filter_seller_type_neq"


def test_seller_type_missing_fails_when_filter_exists(db):
    w = _mk_wishlist(db, "seller_type", "eq", "private")
    listing = _listing(None)
    assert match_listing_to_wishlist(db, w, listing) is False
    assert explain_match(w, listing) == "filter_seller_type_missing"
