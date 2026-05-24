from __future__ import annotations

import uuid
from decimal import Decimal

from app.models.car_listing import CarListing
from app.models.user import User
from app.models.wishlist import Wishlist
from app.models.wishlist_filter import WishlistFilter
from app.services.matching_service import explain_match, match_listing_to_wishlist


def _mk_user(db) -> User:
    u = User(id=uuid.uuid4(), telegram_chat_id=5410199986, username="test-loc-color", is_active=True)
    db.add(u)
    db.commit()
    return u


def _mk_wishlist(db, user: User, query: str, filters: list[tuple[str, str, str]] | None = None) -> Wishlist:
    w = Wishlist(user_id=user.id, query=query, is_active=True)
    db.add(w)
    db.commit()

    for field, op, value in (filters or []):
        db.add(WishlistFilter(wishlist_id=w.id, field=field, operator=op, value=value))
    db.commit()
    db.refresh(w)
    return w


def _mk_listing(**kwargs) -> CarListing:
    base = dict(
        source="olx",
        external_id=str(uuid.uuid4())[:8],
        title="Honda Civic 1994",
        url=f"https://www.olx.com.br/{uuid.uuid4()}",
        price=Decimal("45000"),
        currency="BRL",
    )
    base.update(kwargs)
    return CarListing(**base)


def test_filter_color_eq_with_basic_normalization(db):
    u = _mk_user(db)
    w = _mk_wishlist(db, u, "civic", filters=[("color", "eq", "prata")])

    ok = _mk_listing(color="PRATA")
    bad = _mk_listing(color="preto")

    assert match_listing_to_wishlist(db, w, ok) is True
    assert match_listing_to_wishlist(db, w, bad) is False


def test_filter_city_eq_is_accent_and_case_insensitive(db):
    u = _mk_user(db)
    w = _mk_wishlist(db, u, "civic", filters=[("city", "eq", "Sao Paulo")])

    ok = _mk_listing(city="São Paulo", state="SP")
    bad = _mk_listing(city="Campinas", state="SP")

    assert match_listing_to_wishlist(db, w, ok) is True
    assert match_listing_to_wishlist(db, w, bad) is False


def test_filter_state_eq_accepts_name_or_uf(db):
    u = _mk_user(db)
    w = _mk_wishlist(db, u, "civic", filters=[("state", "eq", "sao paulo")])

    ok = _mk_listing(city="Campinas", state="SP")
    bad = _mk_listing(city="Rio de Janeiro", state="RJ")

    assert match_listing_to_wishlist(db, w, ok) is True
    assert match_listing_to_wishlist(db, w, bad) is False


def test_filter_city_state_fallback_to_location_when_structured_missing(db):
    u = _mk_user(db)
    w = _mk_wishlist(
        db,
        u,
        "civic",
        filters=[("city", "eq", "sao paulo"), ("state", "eq", "sp")],
    )

    ok = _mk_listing(city=None, state=None, location="São Paulo - SP")
    bad = _mk_listing(city=None, state=None, location="Campinas - SP")

    assert match_listing_to_wishlist(db, w, ok) is True
    assert match_listing_to_wishlist(db, w, bad) is False


def test_missing_field_with_active_filter_is_predictably_rejected(db):
    u = _mk_user(db)
    w = _mk_wishlist(db, u, "civic", filters=[("color", "eq", "preto")])

    listing = _mk_listing(color=None)

    assert match_listing_to_wishlist(db, w, listing) is False
    assert explain_match(w, listing) == "filter_color_missing"


def test_invalid_persisted_operators_are_rejected_in_matching(db):
    u = _mk_user(db)
    listing = _mk_listing(city="São Paulo", state="SP", color="vermelho")

    w_city = _mk_wishlist(db, u, "civic", filters=[("city", "gte", "sao paulo")])
    assert match_listing_to_wishlist(db, w_city, listing) is False

    w_color = _mk_wishlist(db, u, "civic", filters=[("color", "gt", "vermelho")])
    assert match_listing_to_wishlist(db, w_color, listing) is False

    w_state = _mk_wishlist(db, u, "civic", filters=[("state", "neq", "SP")])
    assert match_listing_to_wishlist(db, w_state, listing) is False
