"""
Golden-output regression for match_listings_for_active_wishlists.

Captures the CURRENT (pre-refactor) result as a contract.  After the performance
refactor the assertions here must stay green with an identical set of matches.

Design notes:
- Uses a real SQLite DB (the default conftest `db` fixture) including the inverted
  WishlistToken index, so both candidate selection and the matcher run for real.
- Covers: plain query (legacy), relational filters, semantic rules, sold listings,
  inactive wishlists, listings that are candidates for multiple wishlists.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.models.car_listing import CarListing
from app.models.user import User
from app.models.wishlist import Wishlist
from app.models.wishlist_filter import WishlistFilter
from app.services.matching_service import match_listings_for_active_wishlists
from app.services.wishlist_tokens_service import rebuild_tokens_for_wishlist


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _user(db):
    u = User(
        id=uuid.uuid4(),
        telegram_chat_id=5511987654321,
        username="baseline-test",
        is_active=True,
    )
    db.add(u)
    db.flush()
    return u


def _wishlist(db, user_id, query, *, is_active=True, filters=()):
    w = Wishlist(user_id=user_id, query=query, is_active=is_active)
    db.add(w)
    db.flush()
    for field, op, val in filters:
        db.add(WishlistFilter(wishlist_id=w.id, field=field, operator=op, value=val))
    db.flush()
    rebuild_tokens_for_wishlist(db, w)
    db.flush()
    return w


def _listing(db, title, *, source="olx", price=None, year=None, is_sold=False, location=None):
    l = CarListing(
        source=source,
        external_id=str(uuid.uuid4()),
        title=title,
        url=f"https://example.com/{uuid.uuid4()}",
        price=Decimal(str(price)) if price is not None else None,
        currency="BRL",
        year=year,
        is_sold=is_sold,
        location=location,
    )
    db.add(l)
    db.flush()
    return l


# ---------------------------------------------------------------------------
# Golden baseline
# ---------------------------------------------------------------------------

def test_match_listings_for_active_wishlists_golden(db):
    """
    Wishlist coverage:
      w_civic      - plain text query, no filters (legacy path, _get_filters fallback)
      w_civic_si   - query="civic si", has semantic rules (blocks "type r", requires "si")
      w_civic_year - same text as w_civic + year>=2010 relational filter
      w_fiat       - "fiat strada" + price<=50000 relational filter
      w_inactive   - is_active=False, must never appear in results

    Listing coverage:
      L1 "Honda Civic Hatch 2015"  - matches w_civic, w_civic_year; NOT w_civic_si (no "si")
      L2 "Honda Civic SI 1993"     - matches w_civic, w_civic_si; NOT w_civic_year (1993<2010)
      L3 "Fiat Strada 2019" p=45k  - matches w_fiat (price ok); NOT any civic wishlist
      L4 "Fiat Strada 2021" p=65k  - NOT w_fiat (price too high)
      L5 "Honda Civic 2020" SOLD   - never appears anywhere (is_sold=True)
      L6 "Honda Civic Type R 2022" - matches w_civic, w_civic_year; NOT w_civic_si (blocked)
    """
    user = _user(db)

    w_civic = _wishlist(db, user.id, "honda civic")
    w_civic_si = _wishlist(db, user.id, "civic si")
    w_civic_year = _wishlist(db, user.id, "honda civic", filters=[("year", "gte", "2010")])
    w_fiat = _wishlist(db, user.id, "fiat strada", filters=[("price", "lte", "50000")])
    w_inactive = _wishlist(db, user.id, "honda civic", is_active=False)
    db.commit()

    L1 = _listing(db, "Honda Civic Hatch 2015", price=40000, year=2015)
    L2 = _listing(db, "Honda Civic SI 1993 Vermelho", price=30000, year=1993)
    L3 = _listing(db, "Fiat Strada Working 2019", price=45000, year=2019)
    L4 = _listing(db, "Fiat Strada Working 2021", price=65000, year=2021)
    L5 = _listing(db, "Honda Civic 2020", price=80000, year=2020, is_sold=True)
    L6 = _listing(db, "Honda Civic Type R 2022", price=120000, year=2022)
    db.commit()

    out, stats = match_listings_for_active_wishlists(db, [L1, L2, L3, L4, L5, L6])

    # --- per-wishlist per-listing assertions ---

    civic_matches = out.get(w_civic.id) or []
    assert L1 in civic_matches, "L1 should match w_civic"
    assert L2 in civic_matches, "L2 should match w_civic"
    assert L3 not in civic_matches, "L3 (fiat) must not match w_civic"
    assert L4 not in civic_matches, "L4 (fiat) must not match w_civic"
    assert L6 in civic_matches, "L6 (Type R) should match w_civic (no semantic rule here)"

    civic_si_matches = out.get(w_civic_si.id) or []
    assert L2 in civic_si_matches, "L2 (has 'si') should match w_civic_si"
    assert L1 not in civic_si_matches, "L1 (no 'si') must not match w_civic_si"
    assert L6 not in civic_si_matches, "L6 (Type R) blocked or not candidate for w_civic_si"

    civic_year_matches = out.get(w_civic_year.id) or []
    assert L1 in civic_year_matches, "L1 (year=2015>=2010) should match w_civic_year"
    assert L2 not in civic_year_matches, "L2 (year=1993<2010) must not match w_civic_year"
    assert L6 in civic_year_matches, "L6 (year=2022>=2010) should match w_civic_year"

    fiat_matches = out.get(w_fiat.id) or []
    assert L3 in fiat_matches, "L3 (price 45k <= 50k) should match w_fiat"
    assert L4 not in fiat_matches, "L4 (price 65k > 50k) must not match w_fiat"

    # sold listing must never appear
    for wid, matched in out.items():
        assert L5 not in matched, f"Sold L5 must not appear in wishlist {wid}"

    # inactive wishlist must never be in results
    assert w_inactive.id not in out, "Inactive wishlist must not appear in results"

    # stats sanity
    assert isinstance(stats, dict)
    assert stats.get("candidate_wishlists", 0) >= 1


def test_match_listings_for_active_wishlists_empty_input(db):
    """Empty listing list → empty result, no crash."""
    out, stats = match_listings_for_active_wishlists(db, [])
    assert out == {}
    assert stats["candidates_p50"] == 0


def test_match_listings_for_active_wishlists_sold_only(db):
    """All listings sold → no matches."""
    user = _user(db)
    w = _wishlist(db, user.id, "honda civic")
    db.commit()

    sold = _listing(db, "Honda Civic 2020", price=50000, year=2020, is_sold=True)
    db.commit()

    out, _ = match_listings_for_active_wishlists(db, [sold])
    assert w.id not in out
