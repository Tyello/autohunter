from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.core.settings import settings
from app.models.car_listing import CarListing
from app.models.fipe_catalog_entry import FipeCatalogEntry
from app.models.user import User
from app.models.wishlist import Wishlist
from app.services import notifications_queue_service as svc


def _make_user(db):
    """Create a test user."""
    user = User(id=uuid.uuid4(), telegram_chat_id=uuid.uuid4().int % 10_000_000, username=f"u{uuid.uuid4().hex[:8]}", is_active=True)
    db.add(user)
    db.commit()
    return user


def _make_wishlist(db, user=None):
    """Create a test wishlist."""
    if user is None:
        user = _make_user(db)
    wishlist = Wishlist(id=uuid.uuid4(), user_id=user.id, query="honda fit", is_active=True)
    db.add(wishlist)
    db.commit()
    return wishlist


def _make_listing(db, *, make="Honda", model="Fit", year=2008, fuel_type="Gasolina"):
    """Create a test car listing."""
    listing = CarListing(
        id=uuid.uuid4(),
        source="test_source",
        external_id=f"test_{uuid.uuid4().hex[:8]}",
        title=f"{make} {model} {year}",
        url=f"http://test/{uuid.uuid4()}",
        price=Decimal("30000.00"),
        currency="BRL",
        make=make,
        model=model,
        year=year,
        fuel_type=fuel_type,
    )
    db.add(listing)
    db.commit()
    return listing


def _make_catalog_entry(db, *, brand_name="Honda", model_name="Fit", model_year=2008, fuel="Gasolina", price=None, reference_month="2026-08"):
    """Create a test FIPE catalog entry."""
    if price is None:
        price = Decimal("32000.00")
    entry = FipeCatalogEntry(
        id=uuid.uuid4(),
        reference_month=reference_month,
        vehicle_type="car",
        brand_code="25",
        brand_name=brand_name,
        model_code="4828",
        model_name=model_name,
        year_code=f"{model_year}-1",
        model_year=model_year,
        fuel=fuel,
        fipe_code="001004-9",
        price=price,
        currency="BRL",
        source="external_pipeline",
        identity_key=f"codes:25|4828|{model_year}-1",
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


# --- Etapa 6 Tests ---

def test_queue_notifications_uses_fipe_catalog_fallback_when_price_missing(db, monkeypatch):
    """REQ-006: Use catalog fallback when no FipePrice row exists.

    - No FipePrice row for the listing
    - FipeCatalogEntry exists with matching brand/model/year and price
    - score_ad receives the catalog price as fipe_price kwarg
    """
    monkeypatch.setattr(settings, "fipe_lookup_min_confidence", 0.5)

    user = _make_user(db)
    wishlist = _make_wishlist(db, user)
    listing = _make_listing(db, make="Honda", model="Fit", year=2008)

    # Create matching catalog entry (no FipePrice row)
    catalog_entry = _make_catalog_entry(db, brand_name="Honda", model_name="Fit", model_year=2008, price=Decimal("45000.00"))

    # Monkeypatch resolve_listing_to_fipe_candidates to return best_candidate
    captured_kwargs = {}

    def mock_resolve(db_arg, listing=None, reference_month=None, limit=None):
        return {
            "status": "success",
            "best_candidate": {
                "confidence_score": 0.8,
                "catalog_entry_id": catalog_entry.id,
            },
        }

    def mock_score_ad(*args, **kwargs):
        captured_kwargs.update(kwargs)
        # Return a minimal result object
        class MockResult:
            total = 50
            def to_dict(self):
                return {}
        return MockResult()

    monkeypatch.setattr("app.services.notifications_queue_service.resolve_listing_to_fipe_candidates", mock_resolve)
    monkeypatch.setattr("app.services.notifications_queue_service.score_ad", mock_score_ad)

    result = svc.queue_notifications_for_matches(db, wishlist, [listing])

    assert result == 1
    assert captured_kwargs.get("fipe_price") == Decimal("45000.00")


def test_queue_notifications_fallback_respects_min_confidence(db, monkeypatch):
    """REQ-006/007: Fallback returns None when confidence < min_confidence.

    - FipeCatalogEntry exists but confidence is below fipe_lookup_min_confidence
    - score_ad receives None for fipe_price
    """
    monkeypatch.setattr(settings, "fipe_lookup_min_confidence", 0.7)

    user = _make_user(db)
    wishlist = _make_wishlist(db, user)
    listing = _make_listing(db, make="Honda", model="Fit", year=2008)

    # Create catalog entry but with low confidence
    catalog_entry = _make_catalog_entry(db, brand_name="Honda", model_name="Fit", model_year=2010, price=Decimal("45000.00"))

    captured_kwargs = {}

    def mock_resolve(db_arg, listing=None, reference_month=None, limit=None):
        return {
            "status": "success",
            "best_candidate": {
                "confidence_score": 0.5,  # Below min_confidence of 0.7
                "catalog_entry_id": catalog_entry.id,
            },
        }

    def mock_score_ad(*args, **kwargs):
        captured_kwargs.update(kwargs)
        class MockResult:
            total = 50
            def to_dict(self):
                return {}
        return MockResult()

    monkeypatch.setattr("app.services.notifications_queue_service.resolve_listing_to_fipe_candidates", mock_resolve)
    monkeypatch.setattr("app.services.notifications_queue_service.score_ad", mock_score_ad)

    result = svc.queue_notifications_for_matches(db, wishlist, [listing])

    assert result == 1
    assert captured_kwargs.get("fipe_price") is None


def test_queue_notifications_fallback_never_raises_on_resolver_error(db, monkeypatch):
    """REQ-007: Fallback never raises exceptions, even if resolver fails.

    - resolve_listing_to_fipe_candidates raises an exception
    - queue_notifications_for_matches still succeeds
    - score_ad receives None for fipe_price (fallback caught the error)
    """
    monkeypatch.setattr(settings, "fipe_lookup_min_confidence", 0.5)

    user = _make_user(db)
    wishlist = _make_wishlist(db, user)
    listing = _make_listing(db, make="Honda", model="Fit", year=2008)

    captured_kwargs = {}

    def mock_resolve_error(db_arg, listing=None, reference_month=None, limit=None):
        raise RuntimeError("Resolver exploded")

    def mock_score_ad(*args, **kwargs):
        captured_kwargs.update(kwargs)
        class MockResult:
            total = 50
            def to_dict(self):
                return {}
        return MockResult()

    monkeypatch.setattr("app.services.notifications_queue_service.resolve_listing_to_fipe_candidates", mock_resolve_error)
    monkeypatch.setattr("app.services.notifications_queue_service.score_ad", mock_score_ad)

    # Should not raise even though resolver raises
    result = svc.queue_notifications_for_matches(db, wishlist, [listing])

    assert result == 1
    assert captured_kwargs.get("fipe_price") is None
