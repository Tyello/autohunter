from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
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


# --- Etapa 3 Tests (Reactive FIPE Lookup) ---

def test_enqueue_reactive_fipe_lookup_creates_request_when_fallback_returns_none(db, monkeypatch):
    """PREM-02/03: Create FipeLookupRequest when fallback returns None.

    - listing with make="Audi", model="A4", year extracted from title
    - _fallback_fipe_price_via_catalog monkeypatched to return None
    - Assert that 1 FipeLookupRequest is created with correct make/model/year
    """
    user = _make_user(db)
    wishlist = _make_wishlist(db, user)
    listing = _make_listing(db, make="Audi", model="A4", year=None)
    # Override title to include year so _extract_year can parse it
    listing.title = "Audi A4 2019"
    db.add(listing)
    db.commit()

    def mock_resolve(db_arg, listing=None, reference_month=None, limit=None):
        return {"status": "insufficient_data"}

    def mock_score_ad(*args, **kwargs):
        class MockResult:
            total = 50
            def to_dict(self):
                return {}
        return MockResult()

    monkeypatch.setattr("app.services.notifications_queue_service.resolve_listing_to_fipe_candidates", mock_resolve)
    monkeypatch.setattr("app.services.notifications_queue_service.score_ad", mock_score_ad)

    result = svc.queue_notifications_for_matches(db, wishlist, [listing])

    assert result == 1
    # Check that FipeLookupRequest was created
    from app.models.fipe_lookup_request import FipeLookupRequest
    reqs = db.query(FipeLookupRequest).filter(FipeLookupRequest.wishlist_id == wishlist.id).all()
    assert len(reqs) == 1
    assert reqs[0].listing_make == "Audi"  # normalize_fipe_text preserves case, only normalizes whitespace
    assert reqs[0].listing_model == "A4"   # normalize_fipe_text preserves case, only normalizes whitespace
    assert reqs[0].target_year == 2019
    assert reqs[0].status == "pending"


def test_enqueue_reactive_fipe_lookup_skips_when_pending_request_already_exists(db, monkeypatch):
    """PREM-03: Skip if pending request already exists for same (wishlist, make, model, year).

    - Create a FipeLookupRequest with status='pending' for the same params
    - Call queue_notifications_for_matches
    - Assert no new FipeLookupRequest is created
    """
    from app.models.fipe_lookup_request import FipeLookupRequest

    user = _make_user(db)
    wishlist = _make_wishlist(db, user)
    listing = _make_listing(db, make="Honda", model="Fit", year=2008)

    # Pre-create a pending request
    existing_req = FipeLookupRequest(
        id=uuid.uuid4(),
        wishlist_id=wishlist.id,
        listing_make="Honda",
        listing_model="Fit",
        target_year=2008,
        status="pending",
    )
    db.add(existing_req)
    db.commit()

    def mock_resolve(db_arg, listing=None, reference_month=None, limit=None):
        return {"status": "insufficient_data"}

    def mock_score_ad(*args, **kwargs):
        class MockResult:
            total = 50
            def to_dict(self):
                return {}
        return MockResult()

    monkeypatch.setattr("app.services.notifications_queue_service.resolve_listing_to_fipe_candidates", mock_resolve)
    monkeypatch.setattr("app.services.notifications_queue_service.score_ad", mock_score_ad)

    result = svc.queue_notifications_for_matches(db, wishlist, [listing])

    assert result == 1
    # Verify no new request was created
    reqs = db.query(FipeLookupRequest).filter(FipeLookupRequest.wishlist_id == wishlist.id).all()
    assert len(reqs) == 1  # Still just the pre-existing one


def test_enqueue_reactive_fipe_lookup_skips_within_cooldown_after_skipped(db, monkeypatch):
    """PREM-03: Skip if processed_at is within cooldown window (< 7 days ago).

    - Create a FipeLookupRequest with status='skipped' and processed_at=now (within cooldown)
    - Call queue_notifications_for_matches
    - Assert no new FipeLookupRequest is created
    """
    from app.models.fipe_lookup_request import FipeLookupRequest

    user = _make_user(db)
    wishlist = _make_wishlist(db, user)
    listing = _make_listing(db, make="Honda", model="Fit", year=2008)

    # Pre-create a skipped request with processed_at = now (within 7 day cooldown)
    existing_req = FipeLookupRequest(
        id=uuid.uuid4(),
        wishlist_id=wishlist.id,
        listing_make="Honda",
        listing_model="Fit",
        target_year=2008,
        status="skipped",
        processed_at=datetime.now(timezone.utc),
    )
    db.add(existing_req)
    db.commit()

    def mock_resolve(db_arg, listing=None, reference_month=None, limit=None):
        return {"status": "insufficient_data"}

    def mock_score_ad(*args, **kwargs):
        class MockResult:
            total = 50
            def to_dict(self):
                return {}
        return MockResult()

    monkeypatch.setattr("app.services.notifications_queue_service.resolve_listing_to_fipe_candidates", mock_resolve)
    monkeypatch.setattr("app.services.notifications_queue_service.score_ad", mock_score_ad)

    result = svc.queue_notifications_for_matches(db, wishlist, [listing])

    assert result == 1
    # Verify no new request was created
    reqs = db.query(FipeLookupRequest).filter(FipeLookupRequest.wishlist_id == wishlist.id).all()
    assert len(reqs) == 1  # Still just the pre-existing one


def test_enqueue_reactive_fipe_lookup_retries_after_cooldown_expires(db, monkeypatch):
    """PREM-03: Create new request if cooldown has expired (processed_at > 7 days ago).

    - Create a FipeLookupRequest with status='skipped' and processed_at=8 days ago
    - Call queue_notifications_for_matches
    - Assert a new FipeLookupRequest IS created
    """
    from app.models.fipe_lookup_request import FipeLookupRequest

    user = _make_user(db)
    wishlist = _make_wishlist(db, user)
    listing = _make_listing(db, make="Honda", model="Fit", year=2008)

    # Pre-create a skipped request with processed_at = 8 days ago (outside 7 day cooldown)
    old_processed = datetime.now(timezone.utc) - timedelta(days=8)
    existing_req = FipeLookupRequest(
        id=uuid.uuid4(),
        wishlist_id=wishlist.id,
        listing_make="Honda",
        listing_model="Fit",
        target_year=2008,
        status="skipped",
        processed_at=old_processed,
    )
    db.add(existing_req)
    db.commit()

    def mock_resolve(db_arg, listing=None, reference_month=None, limit=None):
        return {"status": "insufficient_data"}

    def mock_score_ad(*args, **kwargs):
        class MockResult:
            total = 50
            def to_dict(self):
                return {}
        return MockResult()

    monkeypatch.setattr("app.services.notifications_queue_service.resolve_listing_to_fipe_candidates", mock_resolve)
    monkeypatch.setattr("app.services.notifications_queue_service.score_ad", mock_score_ad)

    result = svc.queue_notifications_for_matches(db, wishlist, [listing])

    assert result == 1
    # Verify a new request WAS created
    reqs = db.query(FipeLookupRequest).filter(FipeLookupRequest.wishlist_id == wishlist.id).all()
    assert len(reqs) == 2  # Old one + new one


def test_enqueue_reactive_fipe_lookup_skips_when_make_or_model_missing(db, monkeypatch):
    """PREM-02: Skip if make or model is empty after normalization.

    - Create listing with make=None (will normalize to empty string)
    - Call queue_notifications_for_matches
    - Assert no FipeLookupRequest is created
    """
    from app.models.fipe_lookup_request import FipeLookupRequest

    user = _make_user(db)
    wishlist = _make_wishlist(db, user)
    listing = _make_listing(db, make=None, model="Fit", year=2008)

    def mock_resolve(db_arg, listing=None, reference_month=None, limit=None):
        return {"status": "insufficient_data"}

    def mock_score_ad(*args, **kwargs):
        class MockResult:
            total = 50
            def to_dict(self):
                return {}
        return MockResult()

    monkeypatch.setattr("app.services.notifications_queue_service.resolve_listing_to_fipe_candidates", mock_resolve)
    monkeypatch.setattr("app.services.notifications_queue_service.score_ad", mock_score_ad)

    result = svc.queue_notifications_for_matches(db, wishlist, [listing])

    assert result == 1
    # Verify no request was created
    reqs = db.query(FipeLookupRequest).filter(FipeLookupRequest.wishlist_id == wishlist.id).all()
    assert len(reqs) == 0


def test_enqueue_reactive_fipe_lookup_skips_when_year_not_extractable(db, monkeypatch):
    """PREM-02: Skip if year cannot be extracted (year=None, no parseable year in title/url).

    - Create listing with year=None and title without year
    - Call queue_notifications_for_matches
    - Assert no FipeLookupRequest is created
    """
    from app.models.fipe_lookup_request import FipeLookupRequest

    user = _make_user(db)
    wishlist = _make_wishlist(db, user)
    # Create listing with year=None and title without any year
    listing = CarListing(
        id=uuid.uuid4(),
        source="test_source",
        external_id=f"test_{uuid.uuid4().hex[:8]}",
        title="Honda Fit",  # No year in title
        url="http://test/nodathere",  # No year in URL
        price=Decimal("30000.00"),
        currency="BRL",
        make="Honda",
        model="Fit",
        year=None,  # Explicitly None
        fuel_type="Gasolina",
    )
    db.add(listing)
    db.commit()

    def mock_resolve(db_arg, listing=None, reference_month=None, limit=None):
        return {"status": "insufficient_data"}

    def mock_score_ad(*args, **kwargs):
        class MockResult:
            total = 50
            def to_dict(self):
                return {}
        return MockResult()

    monkeypatch.setattr("app.services.notifications_queue_service.resolve_listing_to_fipe_candidates", mock_resolve)
    monkeypatch.setattr("app.services.notifications_queue_service.score_ad", mock_score_ad)

    result = svc.queue_notifications_for_matches(db, wishlist, [listing])

    assert result == 1
    # Verify no request was created
    reqs = db.query(FipeLookupRequest).filter(FipeLookupRequest.wishlist_id == wishlist.id).all()
    assert len(reqs) == 0


def test_enqueue_reactive_fipe_lookup_never_raises_on_db_error(db, monkeypatch):
    """PREM-02: Never raise exceptions, even if db.add fails.

    - Mock db.add to raise an exception
    - Call queue_notifications_for_matches (which internally calls _enqueue_reactive_fipe_lookup)
    - Assert the function completes without raising
    """
    user = _make_user(db)
    wishlist = _make_wishlist(db, user)
    listing = _make_listing(db, make="Audi", model="A4", year=2019)

    original_add = db.add
    call_count = [0]

    def mock_add(obj):
        call_count[0] += 1
        # Only raise on the FipeLookupRequest add (second add after Notification)
        from app.models.fipe_lookup_request import FipeLookupRequest
        if isinstance(obj, FipeLookupRequest):
            raise RuntimeError("Mocked DB error on FipeLookupRequest")
        return original_add(obj)

    def mock_resolve(db_arg, listing=None, reference_month=None, limit=None):
        return {"status": "insufficient_data"}

    def mock_score_ad(*args, **kwargs):
        class MockResult:
            total = 50
            def to_dict(self):
                return {}
        return MockResult()

    monkeypatch.setattr(db, "add", mock_add)
    monkeypatch.setattr("app.services.notifications_queue_service.resolve_listing_to_fipe_candidates", mock_resolve)
    monkeypatch.setattr("app.services.notifications_queue_service.score_ad", mock_score_ad)

    # Should not raise even though db.add fails for FipeLookupRequest
    result = svc.queue_notifications_for_matches(db, wishlist, [listing])

    assert result == 1  # Notification still queued
    # Verify no FipeLookupRequest exists (because the add failed)
    from app.models.fipe_lookup_request import FipeLookupRequest
    reqs = db.query(FipeLookupRequest).filter(FipeLookupRequest.wishlist_id == wishlist.id).all()
    assert len(reqs) == 0


def test_queue_notifications_diag_sets_score_breakdown(db, monkeypatch):
    """Regression: queue_notifications_for_matches_diag is the variant actually called by
    app/scheduler/jobs.py in production. It must compute score_v2/score_breakdown just like
    queue_notifications_for_matches, otherwise the Telegram FIPE comparison badge
    (delta_vs_fipe_pct) never renders for real notifications.
    """
    user = _make_user(db)
    wishlist = _make_wishlist(db, user)
    listing = _make_listing(db, make="Audi", model="A4", year=2019)

    def mock_resolve(db_arg, listing=None, reference_month=None, limit=None):
        return {"status": "insufficient_data"}

    def mock_score_ad(*args, **kwargs):
        class MockResult:
            total = 50
            def to_dict(self):
                return {"delta_vs_fipe_pct": -12.5}
        return MockResult()

    monkeypatch.setattr("app.services.notifications_queue_service.resolve_listing_to_fipe_candidates", mock_resolve)
    monkeypatch.setattr("app.services.notifications_queue_service.score_ad", mock_score_ad)

    result = svc.queue_notifications_for_matches_diag(db, wishlist, [listing])

    assert result["queued"] == 1
    from app.models.notification import Notification
    notif = db.query(Notification).filter(Notification.wishlist_id == wishlist.id).first()
    assert notif is not None
    assert notif.score_v2 == 50
    assert notif.score_breakdown == {"delta_vs_fipe_pct": -12.5}


def test_queue_notifications_diag_enqueues_reactive_fipe_lookup(db, monkeypatch):
    """Regression: the reactive FIPE bootstrap (spec 010) must fire from the diag variant
    too, since that is the path the scheduler actually calls.
    """
    user = _make_user(db)
    wishlist = _make_wishlist(db, user)
    listing = _make_listing(db, make="Audi", model="A4", year=None)
    listing.title = "Audi A4 2019"
    db.add(listing)
    db.commit()

    def mock_resolve(db_arg, listing=None, reference_month=None, limit=None):
        return {"status": "insufficient_data"}

    def mock_score_ad(*args, **kwargs):
        class MockResult:
            total = 50
            def to_dict(self):
                return {}
        return MockResult()

    monkeypatch.setattr("app.services.notifications_queue_service.resolve_listing_to_fipe_candidates", mock_resolve)
    monkeypatch.setattr("app.services.notifications_queue_service.score_ad", mock_score_ad)

    result = svc.queue_notifications_for_matches_diag(db, wishlist, [listing])

    assert result["queued"] == 1
    from app.models.fipe_lookup_request import FipeLookupRequest
    reqs = db.query(FipeLookupRequest).filter(FipeLookupRequest.wishlist_id == wishlist.id).all()
    assert len(reqs) == 1
    assert reqs[0].listing_make == "Audi"
    assert reqs[0].listing_model == "A4"
    assert reqs[0].target_year == 2019


def test_e2e_fipe_price_flows_from_queue_to_telegram_badge(db):
    """True end-to-end: real score_ad (no mocking) + real format_ad_message.

    Wishlist match -> queue_notifications_for_matches_diag (production scheduler path)
    -> Notification.score_breakdown -> telegram_formatter badge text. Exercises the exact
    chain a real user would see, with no shortcuts on either end. This is the pair of bugs
    a purely unit-level test suite missed: (1) the diag queueing path never computed FIPE/
    score at all, and (2) even when it did, the formatter read delta_vs_fipe_pct from the
    wrong (flat) location while score_v2 nests it under market_context["fipe"].
    """
    from app.models.fipe_price import FipePrice
    from app.models.notification import Notification
    from app.services.fipe_service import current_reference_month, listing_vehicle_keys
    from app.notifications.telegram_formatter import format_ad_message

    user = _make_user(db)
    wishlist = _make_wishlist(db, user)
    listing = _make_listing(db, make="Audi", model="A4", year=2019)

    key = listing_vehicle_keys(listing)[0]
    db.add(FipePrice(
        vehicle_key=key,
        reference_month=current_reference_month(),
        fipe_price=Decimal("32000.00"),
    ))
    db.commit()

    result = svc.queue_notifications_for_matches_diag(db, wishlist, [listing])
    assert result["queued"] == 1

    notif = db.query(Notification).filter(Notification.wishlist_id == wishlist.id).first()
    assert notif is not None
    assert notif.score_breakdown is not None
    fipe_ctx = (notif.score_breakdown.get("market_context") or {}).get("fipe") or {}
    assert fipe_ctx.get("fipe_price") == 32000.0
    assert fipe_ctx.get("delta_vs_fipe_pct") is not None

    # notification_delivery_service attaches score_breakdown onto the listing object
    # before calling format_ad_message; replicate that here.
    listing.score_breakdown = notif.score_breakdown
    payload = format_ad_message(listing)
    assert "FIPE" in payload.text
