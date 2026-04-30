from __future__ import annotations

import uuid
from decimal import Decimal

from app.models.car_listing import CarListing
from app.models.user import User
from app.models.wishlist import Wishlist
from app.models.wishlist_filter import WishlistFilter
from app.services.matching_service import match_listing_to_wishlist


def _mk_user(db) -> User:
    u = User(id=uuid.uuid4(), telegram_chat_id=5410199985, username="test", is_active=True)
    db.add(u)
    db.commit()
    return u


def _mk_wishlist(db, user: User, query: str, filters: list[tuple[str, str, str]] | None = None) -> Wishlist:
    w = Wishlist(user_id=user.id, query=query, is_active=True)
    db.add(w)
    db.commit()

    for field, op, value in (filters or []):
        f = WishlistFilter(wishlist_id=w.id, field=field, operator=op, value=value)
        db.add(f)
    db.commit()
    # garante relationship carregada
    db.refresh(w)
    return w


def test_filter_source_eq_blocks_other_sources(db):
    u = _mk_user(db)
    w = _mk_wishlist(db, u, "civic", filters=[("source", "eq", "olx")])

    listing = CarListing(
        source="mercadolivre",
        external_id="MLB1",
        title="Honda Civic 1994",
        url="https://carro.mercadolivre.com.br/MLB-1-_JM",
        price=Decimal("32000"),
        currency="BRL",
    )

    assert match_listing_to_wishlist(db, w, listing) is False


def test_filter_price_lte_blocks_expensive_listing(db):
    u = _mk_user(db)
    w = _mk_wishlist(db, u, "civic", filters=[("price", "lte", "50000")])

    expensive = CarListing(
        source="olx",
        external_id="1",
        title="Honda Civic 1994",
        url="https://www.olx.com.br/1",
        price=Decimal("60000"),
        currency="BRL",
    )

    cheap = CarListing(
        source="olx",
        external_id="2",
        title="Honda Civic 1994",
        url="https://www.olx.com.br/2",
        price=Decimal("45000"),
        currency="BRL",
    )

    assert match_listing_to_wishlist(db, w, expensive) is False
    assert match_listing_to_wishlist(db, w, cheap) is True


def test_filter_year_gte_parses_year_from_title(db):
    u = _mk_user(db)
    w = _mk_wishlist(db, u, "civic", filters=[("year", "gte", "1990")])

    old = CarListing(
        source="olx",
        external_id="3",
        title="Honda Civic 1989",
        url="https://www.olx.com.br/3",
        price=Decimal("30000"),
        currency="BRL",
    )

    ok = CarListing(
        source="olx",
        external_id="4",
        title="Honda Civic 1994",
        url="https://www.olx.com.br/4",
        price=Decimal("32000"),
        currency="BRL",
    )

    assert match_listing_to_wishlist(db, w, old) is False
    assert match_listing_to_wishlist(db, w, ok) is True


def test_filter_price_accepts_ptbr_format(db):
    """Garante que '90.000,00' funciona (pt-BR)."""
    u = _mk_user(db)
    w = _mk_wishlist(db, u, "civic", filters=[("price", "lte", "90.000,00")])

    listing = CarListing(
        source="olx",
        external_id="5",
        title="Honda Civic 1994",
        url="https://www.olx.com.br/5",
        price=Decimal("89999"),
        currency="BRL",
    )

    assert match_listing_to_wishlist(db, w, listing) is True


def test_filter_mileage_km_lte_blocks_higher_km(db):
    u = _mk_user(db)
    w = _mk_wishlist(db, u, "civic", filters=[("mileage_km", "lte", "90000")])

    high_km = CarListing(
        source="olx",
        external_id="6",
        title="Honda Civic 1994",
        url="https://www.olx.com.br/6",
        price=Decimal("45000"),
        currency="BRL",
        mileage_km=120000,
    )

    ok_km = CarListing(
        source="olx",
        external_id="7",
        title="Honda Civic 1994",
        url="https://www.olx.com.br/7",
        price=Decimal("45000"),
        currency="BRL",
        mileage_km=80000,
    )

    assert match_listing_to_wishlist(db, w, high_km) is False
    assert match_listing_to_wishlist(db, w, ok_km) is True
