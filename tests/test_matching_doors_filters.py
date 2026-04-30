from __future__ import annotations

import uuid
from decimal import Decimal

from app.models.car_listing import CarListing
from app.models.user import User
from app.models.wishlist import Wishlist
from app.models.wishlist_filter import WishlistFilter
from app.services.matching_service import explain_match, match_listing_to_wishlist


def _mk_wishlist(db, op: str, value: str) -> Wishlist:
    u = User(id=uuid.uuid4(), telegram_chat_id=5410201000 + (uuid.uuid4().int % 100000), username=str(uuid.uuid4())[:8], is_active=True)
    db.add(u)
    db.commit()
    w = Wishlist(user_id=u.id, query="civic", is_active=True)
    db.add(w)
    db.commit()
    db.add(WishlistFilter(wishlist_id=w.id, field="doors", operator=op, value=value))
    db.commit()
    db.refresh(w)
    return w


def _listing(doors):
    return CarListing(source="olx", external_id=str(uuid.uuid4()), title="Honda Civic 2019", url=f"https://olx.com/{uuid.uuid4()}", price=Decimal("45000"), currency="BRL", doors=doors)


def test_doors_eq_neq_and_missing(db):
    w_eq = _mk_wishlist(db, "eq", "4")
    assert match_listing_to_wishlist(db, w_eq, _listing(4)) is True
    assert match_listing_to_wishlist(db, w_eq, _listing(2)) is False
    assert explain_match(w_eq, _listing(2)) == "filter_doors_eq"

    w_neq = _mk_wishlist(db, "neq", "2")
    assert match_listing_to_wishlist(db, w_neq, _listing(4)) is True
    assert match_listing_to_wishlist(db, w_neq, _listing(2)) is False
    assert explain_match(w_neq, _listing(2)) == "filter_doors_neq"

    assert match_listing_to_wishlist(db, w_eq, _listing(None)) is False
    assert explain_match(w_eq, _listing(None)) == "filter_doors_missing"


def test_doors_gte_lte_and_between(db):
    w_gte = _mk_wishlist(db, "gte", "4")
    assert match_listing_to_wishlist(db, w_gte, _listing(4)) is True
    assert match_listing_to_wishlist(db, w_gte, _listing(3)) is False

    w_lte = _mk_wishlist(db, "lte", "4")
    assert match_listing_to_wishlist(db, w_lte, _listing(4)) is True
    assert match_listing_to_wishlist(db, w_lte, _listing(5)) is False

    w_between = _mk_wishlist(db, "between", "2,4")
    assert match_listing_to_wishlist(db, w_between, _listing(2)) is True
    assert match_listing_to_wishlist(db, w_between, _listing(3)) is True
    assert match_listing_to_wishlist(db, w_between, _listing(4)) is True
    assert match_listing_to_wishlist(db, w_between, _listing(5)) is False
    assert explain_match(w_between, _listing(5)) == "filter_doors_gt"
