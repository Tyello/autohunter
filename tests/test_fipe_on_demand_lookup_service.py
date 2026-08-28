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


# --- _match_fipe_catalog_item ---


def test_match_fipe_catalog_item_returns_none_when_no_containment():
    """Teste 1: Nenhum item contém o token do query → None."""
    items = [{"Label": "Toyota"}]
    result = svc._match_fipe_catalog_item(items, "honda")
    assert result is None


def test_match_fipe_catalog_item_exact_single_match():
    """Teste 2: Um item exato (Honda/honda) → retorna o item."""
    items = [{"Label": "Honda"}, {"Label": "Toyota"}]
    result = svc._match_fipe_catalog_item(items, "honda")
    assert result == {"Label": "Honda"}


def test_match_fipe_catalog_item_prefers_fewest_extra_tokens():
    """Teste 3: Prefere item com menos tokens extras."""
    items = [
        {"Label": "Fit EX 1.5 16V"},
        {"Label": "Fit"},
        {"Label": "Fit LX 1.5"},
    ]
    result = svc._match_fipe_catalog_item(items, "fit")
    assert result == {"Label": "Fit"}


def test_match_fipe_catalog_item_tiebreaks_by_list_order():
    """Teste 4: Em caso de empate, retorna o primeiro da lista."""
    items = [
        {"Label": "Fit EX"},
        {"Label": "Fit LX"},
    ]
    result = svc._match_fipe_catalog_item(items, "fit")
    assert result == {"Label": "Fit EX"}


# --- _resolve_fipe_brand_and_model ---


def test_resolve_fipe_brand_and_model_success(monkeypatch):
    """Teste 5: Sucesso completo - retorna (brand, model_item, reference_code)."""
    calls = {}

    class FakeClient:
        def get_latest_reference_table(self):
            return {"Codigo": 320, "Mes": "agosto/2026"}

        def get_brands(self, reference_code):
            calls["get_brands"] = reference_code
            return [{"Label": "Honda", "Value": "22"}]

        def get_models(self, reference_code, brand_code):
            calls["get_models"] = (reference_code, brand_code)
            return [{"Label": "Fit", "Value": "4828"}]

    monkeypatch.setattr(svc, "FipeApiClient", FakeClient)
    client = svc.FipeApiClient()

    result = svc._resolve_fipe_brand_and_model(client, make="honda", model="fit")

    assert result == ({"Label": "Honda", "Value": "22"}, {"Label": "Fit", "Value": "4828"}, 320)
    assert calls["get_brands"] == 320
    assert calls["get_models"] == (320, "22")


def test_resolve_fipe_brand_and_model_returns_none_when_brand_not_found(monkeypatch):
    """Teste 6: Marca não encontrada - retorna None sem chamar get_models."""
    calls = {}

    class FakeClient:
        def get_latest_reference_table(self):
            return {"Codigo": 320, "Mes": "agosto/2026"}

        def get_brands(self, reference_code):
            calls["get_brands"] = True
            return [{"Label": "Toyota", "Value": "1"}]

        def get_models(self, reference_code, brand_code):
            calls["get_models"] = True
            raise AssertionError("get_models não deveria ser chamado quando marca não é encontrada")

    monkeypatch.setattr(svc, "FipeApiClient", FakeClient)
    client = svc.FipeApiClient()

    result = svc._resolve_fipe_brand_and_model(client, make="honda", model="fit")

    assert result is None
    assert calls.get("get_brands") is True
    assert calls.get("get_models") is None


def test_resolve_fipe_brand_and_model_returns_none_when_model_not_found(monkeypatch):
    """Teste 7: Modelo não encontrado - retorna None."""
    class FakeClient:
        def get_latest_reference_table(self):
            return {"Codigo": 320, "Mes": "agosto/2026"}

        def get_brands(self, reference_code):
            return [{"Label": "Honda", "Value": "22"}]

        def get_models(self, reference_code, brand_code):
            return [{"Label": "Civic", "Value": "9"}]

    monkeypatch.setattr(svc, "FipeApiClient", FakeClient)
    client = svc.FipeApiClient()

    result = svc._resolve_fipe_brand_and_model(client, make="honda", model="fit")

    assert result is None


# --- _bootstrap_fipe_catalog_entry ---


def test_bootstrap_creates_new_catalog_entry(db, monkeypatch):
    """Teste 8: Bootstrap cria nova entrada no catálogo com todos os campos persistidos."""
    class FakeClient:
        def get_model_years(self, reference_code, brand_code, model_code):
            return [{"Label": "2019 Gasolina", "Value": "2019-1"}]

        def get_price(self, reference_code, brand_code, model_code, model_year, fuel_code):
            return {
                "Marca": "Honda",
                "Modelo": "Fit",
                "AnoModelo": 2019,
                "Combustivel": "Gasolina",
                "CodigoFipe": "001004-9",
                "Valor": "R$ 65.000,00",
            }

    monkeypatch.setattr(svc, "FipeApiClient", FakeClient)
    client = svc.FipeApiClient()

    # Call bootstrap
    brand = {"Label": "Honda", "Value": "22"}
    model = {"Label": "Fit", "Value": "4828"}
    result = svc._bootstrap_fipe_catalog_entry(db, client, brand=brand, model=model, reference_code=320, year=2019)

    # Assert return value
    assert result is True

    # Assert database entry was created with correct fields
    entry = db.query(FipeCatalogEntry).filter(
        FipeCatalogEntry.brand_code == "22",
        FipeCatalogEntry.model_code == "4828",
        FipeCatalogEntry.model_year == 2019,
    ).first()
    assert entry is not None
    assert entry.brand_name == "Honda"
    assert entry.model_name == "Fit"
    assert entry.fuel == "Gasolina"
    assert entry.fipe_code == "001004-9"
    assert entry.price == Decimal("65000.00")
    assert entry.source == "on_demand_bootstrap"


def test_bootstrap_returns_false_when_year_not_found(db, monkeypatch):
    """Teste 9: Retorna False quando ano não existe; get_price nunca é chamado."""
    call_count = {"get_price": 0}

    class FakeClient:
        def get_model_years(self, reference_code, brand_code, model_code):
            # Return 2020 data, but we'll request 2019
            return [{"Label": "2020 Gasolina", "Value": "2020-1"}]

        def get_price(self, reference_code, brand_code, model_code, model_year, fuel_code):
            call_count["get_price"] += 1
            return {"Marca": "Honda", "Modelo": "Fit"}

    monkeypatch.setattr(svc, "FipeApiClient", FakeClient)
    client = svc.FipeApiClient()

    brand = {"Label": "Honda", "Value": "22"}
    model = {"Label": "Fit", "Value": "4828"}
    result = svc._bootstrap_fipe_catalog_entry(db, client, brand=brand, model=model, reference_code=320, year=2019)

    # Assert return value
    assert result is False

    # Assert get_price was never called
    assert call_count["get_price"] == 0

    # Assert no new entries were created
    entries = db.query(FipeCatalogEntry).filter(
        FipeCatalogEntry.brand_code == "22",
        FipeCatalogEntry.model_code == "4828",
    ).all()
    assert len(entries) == 0


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


def test_enqueue_logs_error_to_system_logs_on_exception(db, monkeypatch):
    from app.services import system_logs_service

    monkeypatch.setattr(settings, "fipe_lookup_enabled", True)
    wishlist = _make_wishlist(db)

    def boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(db, "commit", boom)

    log_calls = []
    original_log = system_logs_service.log

    def capture_log(db_param, level, component, event, payload=None):
        log_calls.append({
            "level": level,
            "component": component,
            "event": event,
            "payload": payload,
        })

    monkeypatch.setattr(system_logs_service, "log", capture_log)

    request = svc.enqueue_fipe_lookup_for_wishlist(db, wishlist)

    assert request is None
    assert len(log_calls) == 1
    assert log_calls[0]["level"] == "error"
    assert log_calls[0]["component"] == "fipe_lookup"
    assert log_calls[0]["event"] == "enqueue_failed"
    assert log_calls[0]["payload"]["wishlist_id"] == str(wishlist.id)
    assert "error" in log_calls[0]["payload"]


# --- pseudo listing ---

def test_pseudo_listing_single_token_query(db):
    wishlist = _make_wishlist(db, query="civic")
    listing = svc._build_pseudo_listing(wishlist, [], db)
    assert listing.make == "civic"
    assert listing.model == "civic"


def test_pseudo_listing_multi_token_query(db):
    wishlist = _make_wishlist(db, query="honda civic touring")
    listing = svc._build_pseudo_listing(wishlist, [], db)
    assert listing.make == "honda"
    assert listing.model == "civic touring"


def test_pseudo_listing_year_prefers_gte(db):
    wishlist = _make_wishlist(db, year_gte=2018, year_lte=2020)
    filters = db.query(WishlistFilter).filter(WishlistFilter.wishlist_id == wishlist.id).all()
    listing = svc._build_pseudo_listing(wishlist, filters, db)
    assert listing.year == 2018


def test_pseudo_listing_no_year_filter_is_none(db):
    wishlist = _make_wishlist(db)
    listing = svc._build_pseudo_listing(wishlist, [], db)
    assert listing.year is None


def test_pseudo_listing_year_default_unchanged_prefers_gte(db):
    """Etapa 3, teste 6: chamada sem parâmetro year deve usar comportamento padrão (gte se houver)."""
    wishlist = _make_wishlist(db, year_gte=2018, year_lte=2020)
    filters = db.query(WishlistFilter).filter(WishlistFilter.wishlist_id == wishlist.id).all()
    # Sem passar year, deve preferir gte (2018)
    listing = svc._build_pseudo_listing(wishlist, filters, db)
    assert listing.year == 2018


def test_pseudo_listing_year_explicit_overrides_filters(db):
    """Etapa 3, teste 7: parâmetro year explícito (não _UNSET) deve sobrescrever filters."""
    wishlist = _make_wishlist(db, year_gte=2018, year_lte=2020)
    filters = db.query(WishlistFilter).filter(WishlistFilter.wishlist_id == wishlist.id).all()
    # Passando year=2005 explicitamente, deve usar 2005 em vez de gte (2018)
    listing = svc._build_pseudo_listing(wishlist, filters, db, year=2005)
    assert listing.year == 2005


def test_pseudo_listing_year_explicit_none_overrides_filters(db):
    """Etapa 3, teste 7b: parâmetro year=None explícito deve sobrescrever filters."""
    wishlist = _make_wishlist(db, year_gte=2018, year_lte=2020)
    filters = db.query(WishlistFilter).filter(WishlistFilter.wishlist_id == wishlist.id).all()
    # Passando year=None explicitamente, deve usar None em vez de gte (2018)
    listing = svc._build_pseudo_listing(wishlist, filters, db, year=None)
    assert listing.year is None


def test_pseudo_listing_brand_detected_when_not_first_token(db):
    """Etapa 3, teste 8: marca não-primeira palavra (fit honda) deve ser detectada no catálogo."""
    _make_catalog_entry(db)  # Cria Honda Civic
    wishlist = _make_wishlist(db, query="fit honda")
    filters = db.query(WishlistFilter).filter(WishlistFilter.wishlist_id == wishlist.id).all()
    listing = svc._build_pseudo_listing(wishlist, filters, db)
    # "honda" é marca conhecida no catálogo, "fit" é modelo restante
    assert listing.make == "Honda"
    assert listing.model == "fit"


def test_pseudo_listing_brand_detected_honda_fit_s(db):
    """Etapa 3, teste 9: query "honda fit s" com Honda no catálogo → make=Honda, model="fit s"."""
    _make_catalog_entry(db)  # Cria Honda Civic
    wishlist = _make_wishlist(db, query="honda fit s")
    filters = db.query(WishlistFilter).filter(WishlistFilter.wishlist_id == wishlist.id).all()
    listing = svc._build_pseudo_listing(wishlist, filters, db)
    # "honda" é marca conhecida no catálogo, "fit s" são tokens restantes
    assert listing.make == "Honda"
    assert listing.model == "fit s"


def test_pseudo_listing_falls_back_to_legacy_when_no_known_brand(db):
    """Etapa 3, teste 10: fallback a heurística legada quando nenhuma marca é detectada."""
    # Cria marca Honda no catálogo
    _make_catalog_entry(db)
    # Query sem nenhuma marca conhecida
    wishlist = _make_wishlist(db, query="Foo Bar")
    filters = db.query(WishlistFilter).filter(WishlistFilter.wishlist_id == wishlist.id).all()
    listing = svc._build_pseudo_listing(wishlist, filters, db)
    # Fallback: primeiro token = make, resto = model
    assert listing.make == "Foo"
    assert listing.model == "Bar"


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


# Testes para _resolve_target_years (Etapa 2)


def test_resolve_target_years_no_bounds_returns_empty():
    """Caso 1: sem bounds (gte=None, lte=None) retorna lista vazia."""
    from app.services.fipe_on_demand_lookup_service import _resolve_target_years

    result = _resolve_target_years(gte=None, lte=None, current_year=2026, max_years=5)
    assert result == []


def test_resolve_target_years_small_range_returns_all():
    """Caso 2: range pequeno [gte, lte] dentro de max_years retorna todos os anos."""
    from app.services.fipe_on_demand_lookup_service import _resolve_target_years

    result = _resolve_target_years(gte=2020, lte=2022, current_year=2026, max_years=5)
    assert result == [2020, 2021, 2022]


def test_resolve_target_years_gte_only_anchors_on_current_year():
    """Caso 3: apenas gte, âncora em current_year, últimos max_years."""
    from app.services.fipe_on_demand_lookup_service import _resolve_target_years

    result = _resolve_target_years(gte=2018, lte=None, current_year=2026, max_years=5)
    assert result == [2022, 2023, 2024, 2025, 2026]


def test_resolve_target_years_lte_only_anchors_on_lte():
    """Caso 4: apenas lte, âncora em lte, últimos max_years finalizando em lte."""
    from app.services.fipe_on_demand_lookup_service import _resolve_target_years

    result = _resolve_target_years(gte=None, lte=2008, current_year=2026, max_years=5)
    assert result == [2004, 2005, 2006, 2007, 2008]


def test_resolve_target_years_both_bounds_clipped_anchor():
    """Caso 5: ambos bounds, âncora em lte, clipa aos últimos max_years, filtra gte."""
    from app.services.fipe_on_demand_lookup_service import _resolve_target_years

    result = _resolve_target_years(gte=1990, lte=2000, current_year=2026, max_years=5)
    assert result == [1996, 1997, 1998, 1999, 2000]


def test_resolve_target_years_both_bounds_anchors_on_current_year_when_inside_range():
    """Caso 5b: ambos bounds, current_year dentro do range, âncora em current_year."""
    from app.services.fipe_on_demand_lookup_service import _resolve_target_years

    result = _resolve_target_years(gte=2010, lte=2030, current_year=2026, max_years=5)
    assert result == [2024, 2025, 2026, 2027, 2028]


# Testes para _process_one_fipe_lookup loop (Etapa 4)


def test_process_loops_years_stops_on_first_success(db, monkeypatch):
    """Teste 11: Loop com múltiplos anos-alvo, candidato fresco em apenas um ano.

    Wishlist com year_gte=2020, year_lte=2022 (3 anos). Catálogo tem:
    - 2020: nenhum candidato -> bootstrap tenta mas marca não resolve
    - 2021: candidato fresco -> retorna done
    - 2022: não processado (loop parou após sucesso em 2021)

    Esperado: outcomes com pelo menos 2 entradas (2020=skipped_year, 2021=done),
    final_status=done, get_brands chamado no máximo 1 vez (cache de resolução).
    """
    wishlist = _make_wishlist(db, query="honda civic", year_gte=2020, year_lte=2022)
    fresh_at = datetime.now(timezone.utc) - timedelta(days=1)
    entry_2021 = _make_catalog_entry(db, updated_at=fresh_at, model_year=2021, fuel="Gasolina")
    request = FipeLookupRequest(id=uuid.uuid4(), wishlist_id=wishlist.id)
    db.add(request)
    db.commit()

    # Mock resolve_listing_to_fipe_candidates para simular:
    # 2020 -> no_match (desencadeia bootstrap)
    # 2021 -> match com entry_2021 (candidato fresco, continua sem bootstrap)
    # 2022 -> pode ou não ser processado dependendo do loop
    call_count = {"n": 0}

    def mock_resolve(db_arg, listing, reference_month, limit):
        call_count["n"] += 1
        year_arg = listing.year
        if year_arg == 2020:
            return {"status": "no_match", "best_candidate": None}
        elif year_arg == 2021:
            return {"status": "matched", "best_candidate": {"catalog_entry_id": str(entry_2021.id), "confidence_score": 90}}
        elif year_arg == 2022:
            return {"status": "no_match", "best_candidate": None}
        else:
            raise AssertionError(f"year {year_arg} não esperado")

    monkeypatch.setattr(svc, "resolve_listing_to_fipe_candidates", mock_resolve)

    # FakeClient que simula bootstrap fail (marca não resolve)
    # Retorna marcas que NÃO contêm "honda" para simular no match
    api_calls = {"get_brands": 0, "get_models": 0, "get_model_years": 0, "get_price": 0}

    class FakeClient:
        def get_latest_reference_table(self):
            return {"Codigo": 320, "Mes": "agosto/2026"}

        def get_brands(self, reference_code):
            api_calls["get_brands"] += 1
            # Retorna lista SEM Honda -> _resolve_fipe_brand_and_model retorna None
            return [{"Label": "Toyota", "Value": "1"}, {"Label": "Ford", "Value": "3"}]

        def get_models(self, reference_code, brand_code):
            api_calls["get_models"] += 1
            raise AssertionError("get_models não deveria ser chamado se marca não resolve")

        def get_model_years(self, reference_code, brand_code, model_code):
            api_calls["get_model_years"] += 1
            raise AssertionError("get_model_years não deveria ser chamado se marca não resolve")

        def get_price(self, reference_code, brand_code, model_code, model_year, fuel_code):
            api_calls["get_price"] += 1
            raise AssertionError("get_price não deveria ser chamado se marca não resolve")

    monkeypatch.setattr(svc, "FipeApiClient", FakeClient)

    out = svc.process_pending_fipe_lookups(db, limit=10)

    db.refresh(request)
    assert request.status == "done"
    assert out["done"] == 1
    assert out["claimed"] == 1
    # Verificar que resolve foi chamado (pelo menos 2 vezes: 2020 e 2021)
    assert call_count["n"] >= 2
    # Verificar que get_brands foi chamado no máximo 1 vez (cache de resolução entre anos)
    assert api_calls["get_brands"] <= 1, f"get_brands foi chamado {api_calls['get_brands']} vezes, esperado máximo 1"
    # Verificar que outros métodos nunca foram chamados (marca não resolveu)
    assert api_calls["get_models"] == 0
    assert api_calls["get_model_years"] == 0
    assert api_calls["get_price"] == 0


def test_process_loops_years_refreshes_all_then_succeeds(db, monkeypatch):
    """Teste 12: Loop com múltiplos anos-alvo, candidato stale em todos, refresh bem-sucedido.

    Wishlist com year_gte=2020, year_lte=2021 (2 anos). Catálogo tem:
    - 2020: candidato stale
    - 2021: candidato stale

    Refresh bem-sucedido em ambos. Esperado: outcomes com 2 entradas (ambas com status="refreshed"),
    final_status=done
    """
    wishlist = _make_wishlist(db, query="toyota corolla", year_gte=2020, year_lte=2021)
    stale_at = datetime.now(timezone.utc) - timedelta(days=60)
    entry_2020 = _make_catalog_entry(db, updated_at=stale_at, model_year=2020, fuel="Gasolina")
    entry_2021 = _make_catalog_entry(db, updated_at=stale_at, model_year=2021, fuel="Gasolina")
    request = FipeLookupRequest(id=uuid.uuid4(), wishlist_id=wishlist.id)
    db.add(request)
    db.commit()

    call_count = {"resolve": 0, "refresh": 0}

    def mock_resolve(db_arg, listing, reference_month, limit):
        call_count["resolve"] += 1
        year_arg = listing.year
        entry_to_use = entry_2020 if year_arg == 2020 else entry_2021
        return {"status": "matched", "best_candidate": {"catalog_entry_id": str(entry_to_use.id), "confidence_score": 90}}

    def mock_refresh(db_arg, entry):
        call_count["refresh"] += 1
        # Simula sucesso no refresh

    monkeypatch.setattr(svc, "resolve_listing_to_fipe_candidates", mock_resolve)
    monkeypatch.setattr(svc, "_refresh_fipe_catalog_entry", mock_refresh)

    out = svc.process_pending_fipe_lookups(db, limit=10)

    db.refresh(request)
    assert request.status == "done"
    assert out["refreshed"] == 1
    assert call_count["resolve"] == 2  # Ambos anos foram processados
    assert call_count["refresh"] == 2  # Ambos foram refreshados


def test_process_loops_years_all_insufficient_data_marks_skipped(db, monkeypatch):
    """Teste 13: Loop com múltiplos anos-alvo, todos dão insufficient_data.

    Wishlist com year_gte=2020, year_lte=2021 (2 anos). Catálogo vazio.
    resolve_listing_to_fipe_candidates retorna insufficient_data para ambos os anos.

    Esperado: outcomes com 2 entradas (ambas com status="skipped_year"), final_status=skipped
    """
    from app.services import fipe_catalog_resolver_service

    wishlist = _make_wishlist(db, query="ford focus", year_gte=2020, year_lte=2021)
    request = FipeLookupRequest(id=uuid.uuid4(), wishlist_id=wishlist.id)
    db.add(request)
    db.commit()

    def mock_resolve(db_arg, listing, reference_month, limit):
        # Simula insufficient_data para todos os anos
        return {"status": "insufficient_data", "best_candidate": None}

    def mock_log(*args, **kwargs):
        # Mock system_logs para não falhar
        pass

    def mock_ensure_month(db_arg, month_arg):
        # Mock _ensure_month para retornar "2026-07"
        return "2026-07"

    monkeypatch.setattr(svc, "resolve_listing_to_fipe_candidates", mock_resolve)
    monkeypatch.setattr(svc.system_logs_service, "log", mock_log)
    monkeypatch.setattr(svc, "_ensure_month", mock_ensure_month)

    out = svc.process_pending_fipe_lookups(db, limit=10)

    db.refresh(request)
    assert request.status == "skipped"
    assert out["skipped"] == 1


def test_process_logs_diagnostic_payload_per_target_year(db, monkeypatch):
    """Etapa 4, teste 11 (REQ-004): Diagnóstico em system_logs com outcomes por ano-alvo.

    Wishlist com year_gte=2020, year_lte=2022 (3 anos-alvo, todos sem candidato no catálogo).
    Após _process_one_fipe_lookup, assert que system_logs_service.log foi chamado com:
    - component="fipe_lookup"
    - payload["outcomes"] tem 3 entradas (uma por ano-alvo) com chaves year/status/confidence_score
    - payload["final_status"] == "skipped"
    """
    wishlist = _make_wishlist(db, query="ford focus", year_gte=2020, year_lte=2022)
    request = FipeLookupRequest(id=uuid.uuid4(), wishlist_id=wishlist.id)
    db.add(request)
    db.commit()

    def mock_resolve(db_arg, listing, reference_month, limit):
        # Todos os anos retornam no_match
        return {"status": "no_match", "best_candidate": None}

    def mock_ensure_month(db_arg, month_arg):
        # Retorna "2026-07"
        return "2026-07"

    # Capturar as chamadas a system_logs_service.log
    log_calls = []

    def capture_log(db_param, level, component, event, payload=None):
        log_calls.append({
            "level": level,
            "component": component,
            "event": event,
            "payload": payload,
        })

    monkeypatch.setattr(svc, "resolve_listing_to_fipe_candidates", mock_resolve)
    monkeypatch.setattr(svc, "_ensure_month", mock_ensure_month)
    monkeypatch.setattr(svc.system_logs_service, "log", capture_log)

    out = svc.process_pending_fipe_lookups(db, limit=10)

    db.refresh(request)
    assert request.status == "skipped"
    assert out["skipped"] == 1

    # Verificar que system_logs foi chamado com o payload de diagnóstico
    assert len(log_calls) >= 1
    # Encontrar a chamada com outcomes
    log_with_outcomes = None
    for call in log_calls:
        if call.get("component") == "fipe_lookup" and call.get("payload") and "outcomes" in call["payload"]:
            log_with_outcomes = call
            break

    assert log_with_outcomes is not None, "Nenhuma chamada a system_logs com outcomes foi encontrada"
    assert log_with_outcomes["component"] == "fipe_lookup"
    assert log_with_outcomes["payload"]["final_status"] == "skipped"

    # Verificar que outcomes tem 3 entradas (uma por ano-alvo)
    outcomes = log_with_outcomes["payload"]["outcomes"]
    assert len(outcomes) == 3, f"Expected 3 outcomes, got {len(outcomes)}"

    # Verificar que cada outcome tem as chaves requeridas
    for i, outcome in enumerate(outcomes):
        assert "year" in outcome, f"Outcome {i} missing 'year'"
        assert "status" in outcome, f"Outcome {i} missing 'status'"
        assert "confidence_score" in outcome, f"Outcome {i} missing 'confidence_score'"

    # Verificar que os anos-alvo estão corretos
    years_in_outcomes = sorted([o["year"] for o in outcomes])
    assert years_in_outcomes == [2020, 2021, 2022]


# --- Bootstrap tests (Etapa 4) ---


def test_process_attempts_bootstrap_when_no_local_candidate(db, monkeypatch):
    """Teste 10 (REQ-001): Tenta bootstrap quando não há candidato local."""
    wishlist = _make_wishlist(db, query="honda fit", year_gte=2019, year_lte=2020)
    _make_catalog_entry(db)  # Create some catalog data so _ensure_month works
    request = FipeLookupRequest(id=uuid.uuid4(), wishlist_id=wishlist.id)
    db.add(request)
    db.commit()

    # Mock resolve_listing_to_fipe_candidates to always return no_match
    monkeypatch.setattr(
        svc,
        "resolve_listing_to_fipe_candidates",
        lambda *a, **k: {"status": "no_match", "best_candidate": None},
    )

    # Setup FakeClient para resolve + bootstrap sucesso
    class FakeClient:
        def get_latest_reference_table(self):
            return {"Codigo": 320, "Mes": "agosto/2026"}

        def get_brands(self, reference_code):
            return [{"Label": "Honda", "Value": "22"}]

        def get_models(self, reference_code, brand_code):
            return [{"Label": "Fit", "Value": "4828"}]

        def get_model_years(self, reference_code, brand_code, model_code):
            return [{"Label": "2019 Gasolina", "Value": "2019-1"}]

        def get_price(self, reference_code, brand_code, model_code, model_year, fuel_code):
            return {
                "Marca": "Honda",
                "Modelo": "Fit",
                "AnoModelo": 2019,
                "Combustivel": "Gasolina",
                "CodigoFipe": "001004-9",
                "Valor": "R$ 65.000,00",
            }

    monkeypatch.setattr(svc, "FipeApiClient", FakeClient)

    log_calls = []

    def capture_log(db_param, level, component, event, payload=None):
        log_calls.append({"level": level, "component": component, "event": event, "payload": payload})

    monkeypatch.setattr(svc.system_logs_service, "log", capture_log)

    out = svc.process_pending_fipe_lookups(db, limit=10)

    db.refresh(request)
    assert request.status == "done"
    assert out["bootstrapped"] == 1

    # REQ-008: outcome "bootstrapped" deve ser gravado no payload de system_logs
    outcome_calls = [c for c in log_calls if c["component"] == "fipe_lookup" and c["payload"] and "outcomes" in c["payload"]]
    assert len(outcome_calls) == 1
    assert {"year": 2019, "status": "bootstrapped", "confidence_score": None} in outcome_calls[0]["payload"]["outcomes"]


def test_process_skips_year_when_brand_not_matched(db, monkeypatch):
    """Teste 11 (REQ-002): Skip quando marca não bate durante bootstrap."""
    wishlist = _make_wishlist(db, query="honda fit", year_gte=2019, year_lte=2020)
    _make_catalog_entry(db)  # Create some catalog data so _ensure_month works
    request = FipeLookupRequest(id=uuid.uuid4(), wishlist_id=wishlist.id)
    db.add(request)
    db.commit()

    # Mock resolve_listing_to_fipe_candidates to always return no_match
    monkeypatch.setattr(
        svc,
        "resolve_listing_to_fipe_candidates",
        lambda *a, **k: {"status": "no_match", "best_candidate": None},
    )

    # Setup FakeClient onde get_brands não bate com "honda"
    class FakeClient:
        def get_latest_reference_table(self):
            return {"Codigo": 320, "Mes": "agosto/2026"}

        def get_brands(self, reference_code):
            return [{"Label": "Toyota", "Value": "1"}]  # Toyota, não Honda

        def get_models(self, *args, **kwargs):
            raise AssertionError("get_models não deveria ser chamado se marca não bate")

    monkeypatch.setattr(svc, "FipeApiClient", FakeClient)

    out = svc.process_pending_fipe_lookups(db, limit=10)

    db.refresh(request)
    assert request.status == "skipped"
    assert out["skipped"] == 1

    # Verificar que nenhuma FipeCatalogEntry foi criada
    entries = db.query(FipeCatalogEntry).filter(FipeCatalogEntry.brand_code == "22").all()
    assert len(entries) == 0


def test_process_reuses_resolved_brand_model_across_years(db, monkeypatch):
    """Teste 12 (REQ-006): Cache de resolução de marca/modelo entre anos."""
    wishlist = _make_wishlist(db, query="honda fit", year_gte=2018, year_lte=2020)
    _make_catalog_entry(db)  # Create some catalog data so _ensure_month works
    request = FipeLookupRequest(id=uuid.uuid4(), wishlist_id=wishlist.id)
    db.add(request)
    db.commit()

    # Mock resolve_listing_to_fipe_candidates to always return no_match
    monkeypatch.setattr(
        svc,
        "resolve_listing_to_fipe_candidates",
        lambda *a, **k: {"status": "no_match", "best_candidate": None},
    )

    # Setup FakeClient com contadores de chamadas
    calls = {"get_brands": 0, "get_models": 0, "get_model_years": 0, "get_price": 0}

    class FakeClient:
        def get_latest_reference_table(self):
            return {"Codigo": 320, "Mes": "agosto/2026"}

        def get_brands(self, reference_code):
            calls["get_brands"] += 1
            return [{"Label": "Honda", "Value": "22"}]

        def get_models(self, reference_code, brand_code):
            calls["get_models"] += 1
            return [{"Label": "Fit", "Value": "4828"}]

        def get_model_years(self, reference_code, brand_code, model_code):
            calls["get_model_years"] += 1
            # Return 2018, 2019, 2020
            return [
                {"Label": f"{year} Gasolina", "Value": f"{year}-1"}
                for year in [2018, 2019, 2020]
            ]

        def get_price(self, reference_code, brand_code, model_code, model_year, fuel_code):
            calls["get_price"] += 1
            return {
                "Marca": "Honda",
                "Modelo": "Fit",
                "AnoModelo": model_year,
                "Combustivel": "Gasolina",
                "CodigoFipe": "001004-9",
                "Valor": "R$ 65.000,00",
            }

    monkeypatch.setattr(svc, "FipeApiClient", FakeClient)

    out = svc.process_pending_fipe_lookups(db, limit=10)

    db.refresh(request)
    assert request.status == "done"
    # get_brands/get_models chamados exatamente 1 vez (cache reutilizado)
    assert calls["get_brands"] == 1
    assert calls["get_models"] == 1
    # get_model_years/get_price chamados 3 vezes (uma por ano)
    assert calls["get_model_years"] == 3
    assert calls["get_price"] == 3


def test_process_bootstrap_api_error_stops_loop_and_retries(db, monkeypatch):
    """Teste 13 (REQ-007): Erro de API durante bootstrap interrompe loop com retry."""
    wishlist = _make_wishlist(db, query="honda fit", year_gte=2020, year_lte=2021)
    _make_catalog_entry(db)  # Create some catalog data so _ensure_month works
    request = FipeLookupRequest(id=uuid.uuid4(), wishlist_id=wishlist.id)
    db.add(request)
    db.commit()

    # Mock resolve_listing_to_fipe_candidates to always return no_match
    monkeypatch.setattr(
        svc,
        "resolve_listing_to_fipe_candidates",
        lambda *a, **k: {"status": "no_match", "best_candidate": None},
    )

    from app.services.fipe_api_client import FipeApiError

    # Setup FakeClient que levanta erro em get_brands
    class FakeClient:
        def get_latest_reference_table(self):
            return {"Codigo": 320, "Mes": "agosto/2026"}

        def get_brands(self, reference_code):
            raise FipeApiError("timeout da API FIPE")

    monkeypatch.setattr(svc, "FipeApiClient", FakeClient)

    out = svc.process_pending_fipe_lookups(db, limit=10)

    db.refresh(request)
    assert request.attempts == 1
    assert request.status == "pending"
    assert "timeout" in request.last_error
    assert out["failed_temp"] == 1


def test_process_does_not_retry_brand_resolution_after_no_match(db, monkeypatch):
    """Teste 14 (REQ-009): Não retenta resolução de marca após falha."""
    wishlist = _make_wishlist(db, query="honda fit", year_gte=2018, year_lte=2020)
    _make_catalog_entry(db)  # Create some catalog data so _ensure_month works
    request = FipeLookupRequest(id=uuid.uuid4(), wishlist_id=wishlist.id)
    db.add(request)
    db.commit()

    # Mock resolve_listing_to_fipe_candidates to always return no_match
    monkeypatch.setattr(
        svc,
        "resolve_listing_to_fipe_candidates",
        lambda *a, **k: {"status": "no_match", "best_candidate": None},
    )

    # Setup FakeClient onde get_brands retorna lista sem match
    calls = {"get_brands": 0}

    class FakeClient:
        def get_latest_reference_table(self):
            return {"Codigo": 320, "Mes": "agosto/2026"}

        def get_brands(self, reference_code):
            calls["get_brands"] += 1
            return [{"Label": "Toyota", "Value": "1"}]  # Toyota, não Honda

    monkeypatch.setattr(svc, "FipeApiClient", FakeClient)

    out = svc.process_pending_fipe_lookups(db, limit=10)

    db.refresh(request)
    assert request.status == "skipped"
    # get_brands deve ser chamado exatamente 1 vez, não 3 (uma por ano)
    assert calls["get_brands"] == 1
