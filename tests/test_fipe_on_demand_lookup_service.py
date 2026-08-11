from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.core.settings import settings
from app.models.fipe_catalog_entry import FipeCatalogEntry
from app.models.fipe_lookup_request import FipeLookupRequest
from app.models.user import User
from app.models.wishlist import Wishlist
from app.models.wishlist_filter import WishlistFilter
from app.services.fipe_api_client import FipeApiClient
from app.services import fipe_on_demand_lookup_service as svc


def _make_wishlist(db, *, query="honda civic", year_gte=None, year_lte=None):
    user = User(id=uuid.uuid4(), telegram_chat_id=uuid.uuid4().int % 10_000_000, username=f"u{uuid.uuid4().hex[:8]}", is_active=True)
    db.add(user)
    wishlist = Wishlist(id=uuid.uuid4(), user_id=user.id, query=query, is_active=True)
    db.add(wishlist)
    db.commit()

    filters = []
    if year_gte is not None:
        filters.append(WishlistFilter(id=uuid.uuid4(), wishlist_id=wishlist.id, field="year", operator="gte", value=str(year_gte)))
    if year_lte is not None:
        filters.append(WishlistFilter(id=uuid.uuid4(), wishlist_id=wishlist.id, field="year", operator="lte", value=str(year_lte)))
    for flt in filters:
        db.add(flt)
    if filters:
        db.commit()
    return wishlist


def _make_catalog_entry(db, *, updated_at=None, brand_code="25", model_code="4828", model_year=2019, fuel="Gasolina"):
    entry = FipeCatalogEntry(
        id=uuid.uuid4(),
        reference_month="2026-07",
        vehicle_type="car",
        brand_code=brand_code,
        brand_name="Honda",
        model_code=model_code,
        model_name="Civic",
        year_code=f"{model_year}-1",
        model_year=model_year,
        fuel=fuel,
        fipe_code="001004-9",
        price=Decimal("100000"),
        currency="BRL",
        source="external_pipeline",
        identity_key=f"codes:{brand_code}|{model_code}|{model_year}-1",
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    if updated_at is not None:
        entry.updated_at = updated_at
        db.commit()
        db.refresh(entry)
    return entry


# --- enqueue ---

def test_enqueue_inserts_pending_request(db, monkeypatch):
    monkeypatch.setattr(settings, "fipe_lookup_enabled", True)
    wishlist = _make_wishlist(db)

    request = svc.enqueue_fipe_lookup_for_wishlist(db, wishlist)

    assert request is not None
    assert request.status == "pending"
    assert db.query(FipeLookupRequest).filter(FipeLookupRequest.wishlist_id == wishlist.id).count() == 1


def test_enqueue_skips_when_disabled(db, monkeypatch):
    monkeypatch.setattr(settings, "fipe_lookup_enabled", False)
    wishlist = _make_wishlist(db)

    request = svc.enqueue_fipe_lookup_for_wishlist(db, wishlist)

    assert request is None
    assert db.query(FipeLookupRequest).count() == 0


def test_enqueue_dedupes_existing_pending(db, monkeypatch):
    monkeypatch.setattr(settings, "fipe_lookup_enabled", True)
    wishlist = _make_wishlist(db)

    first = svc.enqueue_fipe_lookup_for_wishlist(db, wishlist)
    second = svc.enqueue_fipe_lookup_for_wishlist(db, wishlist)

    assert first is not None
    assert second is None
    assert db.query(FipeLookupRequest).filter(FipeLookupRequest.wishlist_id == wishlist.id).count() == 1


def test_enqueue_never_raises_on_db_error(db, monkeypatch):
    monkeypatch.setattr(settings, "fipe_lookup_enabled", True)
    wishlist = _make_wishlist(db)

    def boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(db, "commit", boom)

    request = svc.enqueue_fipe_lookup_for_wishlist(db, wishlist)

    assert request is None


# --- pseudo listing ---

def test_pseudo_listing_single_token_query(db):
    wishlist = _make_wishlist(db, query="civic")
    listing = svc._build_pseudo_listing(wishlist, [])
    assert listing.make == "civic"
    assert listing.model == "civic"


def test_pseudo_listing_multi_token_query(db):
    wishlist = _make_wishlist(db, query="honda civic touring")
    listing = svc._build_pseudo_listing(wishlist, [])
    assert listing.make == "honda"
    assert listing.model == "civic touring"


def test_pseudo_listing_year_prefers_gte(db):
    wishlist = _make_wishlist(db, year_gte=2018, year_lte=2020)
    filters = db.query(WishlistFilter).filter(WishlistFilter.wishlist_id == wishlist.id).all()
    listing = svc._build_pseudo_listing(wishlist, filters)
    assert listing.year == 2018


def test_pseudo_listing_no_year_filter_is_none(db):
    wishlist = _make_wishlist(db)
    listing = svc._build_pseudo_listing(wishlist, [])
    assert listing.year is None


# --- process_pending_fipe_lookups ---

def test_process_reuses_fresh_candidate_without_api_call(db, monkeypatch):
    wishlist = _make_wishlist(db, query="honda civic", year_gte=2019)
    entry = _make_catalog_entry(db, updated_at=datetime.now(timezone.utc))
    request = FipeLookupRequest(id=uuid.uuid4(), wishlist_id=wishlist.id)
    db.add(request)
    db.commit()

    monkeypatch.setattr(
        svc,
        "resolve_listing_to_fipe_candidates",
        lambda *a, **k: {"status": "matched", "best_candidate": {"catalog_entry_id": str(entry.id), "confidence_score": 90}},
    )

    class ExplodingClient:
        def __getattr__(self, name):
            raise AssertionError("FipeApiClient não deveria ser instanciado/chamado para candidato fresco")

    monkeypatch.setattr(svc, "FipeApiClient", ExplodingClient)

    out = svc.process_pending_fipe_lookups(db, limit=10)

    db.refresh(request)
    assert request.status == "done"
    assert out["done"] == 1
    assert out["claimed"] == 1


def test_process_refreshes_stale_candidate_via_targeted_api_call(db, monkeypatch):
    wishlist = _make_wishlist(db, query="honda civic", year_gte=2019)
    stale_at = datetime.now(timezone.utc) - timedelta(days=60)
    entry = _make_catalog_entry(db, updated_at=stale_at)
    request = FipeLookupRequest(id=uuid.uuid4(), wishlist_id=wishlist.id)
    db.add(request)
    db.commit()

    monkeypatch.setattr(
        svc,
        "resolve_listing_to_fipe_candidates",
        lambda *a, **k: {"status": "matched", "best_candidate": {"catalog_entry_id": str(entry.id), "confidence_score": 90}},
    )

    calls = {"get_brands": 0, "get_models": 0}

    class FakeClient:
        def get_latest_reference_table(self):
            return {"Codigo": 320, "Mes": "agosto/2026"}

        def get_model_years(self, reference_code, brand_code, model_code):
            return [{"Value": "2019-1", "Label": "2019 Gasolina"}]

        def get_price(self, **kwargs):
            calls["get_price"] = kwargs
            return {
                "Valor": "R$ 93.500,00",
                "Marca": "Honda",
                "Modelo": "Civic",
                "AnoModelo": 2019,
                "Combustivel": "Gasolina",
                "CodigoFipe": "001004-9",
                "MesReferencia": "agosto de 2026",
            }

        def get_brands(self, *a, **k):
            calls["get_brands"] += 1
            raise AssertionError("get_brands não deveria ser chamado em refresh direcionado")

        def get_models(self, *a, **k):
            calls["get_models"] += 1
            raise AssertionError("get_models não deveria ser chamado em refresh direcionado")

    monkeypatch.setattr(svc, "FipeApiClient", FakeClient)

    out = svc.process_pending_fipe_lookups(db, limit=10)

    db.refresh(request)
    assert request.status == "done"
    assert out["refreshed"] == 1
    assert calls["get_brands"] == 0
    assert calls["get_models"] == 0
    assert "get_price" in calls

    new_entries = db.query(FipeCatalogEntry).filter(FipeCatalogEntry.source == "on_demand").all()
    assert len(new_entries) == 1
    assert new_entries[0].price == Decimal("93500.00")


def test_process_retries_then_fails_after_max_attempts(db, monkeypatch):
    wishlist = _make_wishlist(db, query="honda civic", year_gte=2019)
    stale_at = datetime.now(timezone.utc) - timedelta(days=60)
    entry = _make_catalog_entry(db, updated_at=stale_at)
    request = FipeLookupRequest(id=uuid.uuid4(), wishlist_id=wishlist.id)
    db.add(request)
    db.commit()

    monkeypatch.setattr(
        svc,
        "resolve_listing_to_fipe_candidates",
        lambda *a, **k: {"status": "matched", "best_candidate": {"catalog_entry_id": str(entry.id), "confidence_score": 90}},
    )

    class ExplodingClient:
        def get_latest_reference_table(self):
            from app.services.fipe_api_client import FipeApiError

            raise FipeApiError("api indisponivel")

    monkeypatch.setattr(svc, "FipeApiClient", ExplodingClient)

    max_attempts = settings.fipe_lookup_max_attempts
    for i in range(1, max_attempts + 1):
        svc.process_pending_fipe_lookups(db, limit=10)
        db.refresh(request)
        assert request.attempts == i
        if i < max_attempts:
            assert request.status == "pending"
        else:
            assert request.status == "failed"


def test_process_marks_skipped_when_no_candidate(db, monkeypatch):
    wishlist = _make_wishlist(db, query="honda civic", year_gte=2019)
    _make_catalog_entry(db)
    request = FipeLookupRequest(id=uuid.uuid4(), wishlist_id=wishlist.id)
    db.add(request)
    db.commit()

    monkeypatch.setattr(
        svc,
        "resolve_listing_to_fipe_candidates",
        lambda *a, **k: {"status": "no_match", "best_candidate": None},
    )

    out = svc.process_pending_fipe_lookups(db, limit=10)

    db.refresh(request)
    assert request.status == "skipped"
    assert out["skipped"] == 1


def test_process_marks_skipped_when_insufficient_data(db):
    wishlist = _make_wishlist(db, query="civic")
    _make_catalog_entry(db)
    request = FipeLookupRequest(id=uuid.uuid4(), wishlist_id=wishlist.id)
    db.add(request)
    db.commit()

    out = svc.process_pending_fipe_lookups(db, limit=10)

    db.refresh(request)
    assert request.status == "skipped"
    assert out["skipped"] == 1


def test_process_isolates_unexpected_failure_without_aborting_batch(db, monkeypatch):
    wishlist_a = _make_wishlist(db, query="honda civic", year_gte=2019)
    wishlist_b = _make_wishlist(db, query="toyota corolla", year_gte=2019)
    _make_catalog_entry(db)
    request_a = FipeLookupRequest(id=uuid.uuid4(), wishlist_id=wishlist_a.id)
    request_b = FipeLookupRequest(id=uuid.uuid4(), wishlist_id=wishlist_b.id)
    db.add(request_a)
    db.add(request_b)
    db.commit()

    call_count = {"n": 0}
    original = svc._process_one_fipe_lookup

    def flaky(db_arg, request):
        call_count["n"] += 1
        if request.id == request_a.id:
            raise RuntimeError("unexpected bug")
        return original(db_arg, request)

    monkeypatch.setattr(svc, "_process_one_fipe_lookup", flaky)
    monkeypatch.setattr(
        svc,
        "resolve_listing_to_fipe_candidates",
        lambda *a, **k: {"status": "no_match", "best_candidate": None},
    )

    out = svc.process_pending_fipe_lookups(db, limit=10)

    db.refresh(request_a)
    db.refresh(request_b)
    assert call_count["n"] == 2
    assert request_a.status == "pending"
    assert request_a.attempts == 1
    assert request_b.status == "skipped"
    assert out["claimed"] == 2
