from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy.orm import Session

from app.core.settings import settings
from app.models.fipe_catalog_entry import FipeCatalogEntry
from app.models.fipe_lookup_request import FipeLookupRequest
from app.models.wishlist import Wishlist
from app.models.wishlist_filter import WishlistFilter
from app.services.fipe_api_client import FipeApiClient, FipeApiError
from app.services.fipe_catalog_resolver_service import _ensure_month, resolve_listing_to_fipe_candidates
from app.services.fipe_external_pipeline_adapter import normalize_external_fipe_row
from app.services.fipe_monthly_sync_service import upsert_fipe_catalog_entries


def _build_pseudo_listing(wishlist: Wishlist, filters: list[WishlistFilter]) -> SimpleNamespace:
    tokens = (wishlist.query or "").split()
    if not tokens:
        make = model = None
    elif len(tokens) == 1:
        make = model = tokens[0]
    else:
        make = tokens[0]
        model = " ".join(tokens[1:])

    gte_value = None
    lte_value = None
    for flt in filters:
        if getattr(flt, "field", None) != "year":
            continue
        operator = getattr(flt, "operator", None)
        if operator == "gte":
            gte_value = flt.value
        elif operator == "lte":
            lte_value = flt.value

    raw_year = gte_value if gte_value is not None else lte_value
    year = None
    if raw_year is not None:
        try:
            year = int(str(raw_year).strip())
        except (ValueError, TypeError):
            year = None

    return SimpleNamespace(make=make, model=model, year=year, version=None, fuel_type=None, id=wishlist.id)


def enqueue_fipe_lookup_for_wishlist(db: Session, wishlist: Wishlist) -> FipeLookupRequest | None:
    if not settings.fipe_lookup_enabled:
        return None
    try:
        existing = (
            db.query(FipeLookupRequest)
            .filter(FipeLookupRequest.wishlist_id == wishlist.id, FipeLookupRequest.status == "pending")
            .first()
        )
        if existing:
            return None
        request = FipeLookupRequest(id=uuid.uuid4(), wishlist_id=wishlist.id)
        db.add(request)
        db.commit()
        db.refresh(request)
        return request
    except Exception as exc:
        print(f"[fipe_on_demand_lookup] enqueue_failed wishlist_id={wishlist.id} exc_type={type(exc).__name__} err={exc}")
        db.rollback()
        return None


def _mark_skipped(db: Session, request: FipeLookupRequest) -> str:
    request.status = "skipped"
    request.processed_at = datetime.now(timezone.utc)
    db.commit()
    return "skipped"


def _is_fresh(entry: FipeCatalogEntry) -> bool:
    updated_at = entry.updated_at
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.fipe_lookup_freshness_days)
    return updated_at >= cutoff


def _find_target_year(years: list[dict], entry: FipeCatalogEntry) -> dict | None:
    if entry.model_year is None:
        return None
    year_matches = [item for item in (years or []) if str(item.get("Value", "")).split("-", 1)[0] == str(entry.model_year)]
    if not year_matches:
        return None
    if entry.fuel:
        fuel_norm = entry.fuel.strip().lower()
        for item in year_matches:
            if fuel_norm in str(item.get("Label", "")).lower():
                return item
    return year_matches[0]


def _refresh_fipe_catalog_entry(db: Session, entry: FipeCatalogEntry) -> None:
    if not entry.brand_code or not entry.model_code:
        raise FipeApiError(
            f"brand_code/model_code ausentes no candidato catalog_entry_id={entry.id}; refresh direcionado inviável"
        )

    client = FipeApiClient()
    reference_table = client.get_latest_reference_table()
    reference_code = reference_table.get("Codigo")

    years = client.get_model_years(reference_code, entry.brand_code, entry.model_code)
    target = _find_target_year(years, entry)
    if target is None:
        raise FipeApiError(
            f"nenhuma combinação de ano/combustível encontrada para brand_code={entry.brand_code} "
            f"model_code={entry.model_code} model_year={entry.model_year}"
        )

    value = str(target.get("Value") or "")
    fuel_code = value.split("-", 1)[1] if "-" in value else value

    price_data = client.get_price(
        reference_code=reference_code,
        brand_code=entry.brand_code,
        model_code=entry.model_code,
        model_year=entry.model_year,
        fuel_code=fuel_code,
    )

    raw_row = {
        "tipo_veiculo": entry.vehicle_type,
        "marca": price_data.get("Marca"),
        "modelo": price_data.get("Modelo"),
        "ano": price_data.get("AnoModelo"),
        "combustivel": price_data.get("Combustivel"),
        "codigo_fipe": price_data.get("CodigoFipe"),
        "valor": price_data.get("Valor"),
    }
    current_month = datetime.now(timezone.utc).strftime("%Y-%m")
    normalized = normalize_external_fipe_row(raw_row, reference_month=current_month)
    if normalized is None:
        raise FipeApiError("resposta da API FIPE não pôde ser normalizada durante refresh direcionado")

    upsert_fipe_catalog_entries(db, [normalized], reference_month=current_month, source="on_demand")


def _process_one_fipe_lookup(db: Session, request: FipeLookupRequest) -> str:
    wishlist = db.query(Wishlist).filter(Wishlist.id == request.wishlist_id).first()
    if wishlist is None:
        return _mark_skipped(db, request)

    filters = db.query(WishlistFilter).filter(WishlistFilter.wishlist_id == wishlist.id).all()
    pseudo_listing = _build_pseudo_listing(wishlist, filters)

    month = _ensure_month(db, None)
    result = resolve_listing_to_fipe_candidates(db, listing=pseudo_listing, reference_month=month, limit=5)
    best = result.get("best_candidate")
    if result["status"] == "insufficient_data" or best is None:
        return _mark_skipped(db, request)
    if best["confidence_score"] < settings.fipe_lookup_min_confidence:
        return _mark_skipped(db, request)

    try:
        catalog_entry_id = uuid.UUID(str(best["catalog_entry_id"]))
    except (ValueError, TypeError, KeyError):
        return _mark_skipped(db, request)
    entry = db.query(FipeCatalogEntry).filter(FipeCatalogEntry.id == catalog_entry_id).first()
    if entry is None:
        return _mark_skipped(db, request)

    if _is_fresh(entry):
        request.status = "done"
        request.processed_at = datetime.now(timezone.utc)
        db.commit()
        return "done"

    try:
        _refresh_fipe_catalog_entry(db, entry)
    except Exception as exc:
        db.rollback()
        request.attempts += 1
        request.last_error = str(exc)[:1000]
        if request.attempts >= settings.fipe_lookup_max_attempts:
            request.status = "failed"
            request.processed_at = datetime.now(timezone.utc)
            db.commit()
            return "failed_final"
        request.status = "pending"
        db.commit()
        return "failed_temp"

    request.status = "done"
    request.processed_at = datetime.now(timezone.utc)
    db.commit()
    return "refreshed"


def process_pending_fipe_lookups(db: Session, *, limit: int | None = None) -> dict:
    batch_limit = int(limit if limit is not None else settings.fipe_lookup_batch_size)
    counters = {"claimed": 0, "done": 0, "skipped": 0, "refreshed": 0, "failed_temp": 0, "failed_final": 0}

    pending = (
        db.query(FipeLookupRequest)
        .filter(FipeLookupRequest.status == "pending")
        .order_by(FipeLookupRequest.created_at)
        .limit(batch_limit)
        .all()
    )

    for request in pending:
        request.status = "processing"
        db.commit()
        counters["claimed"] += 1
        try:
            outcome = _process_one_fipe_lookup(db, request)
            counters[outcome] += 1
        except Exception as exc:
            db.rollback()
            request.attempts += 1
            request.last_error = str(exc)[:1000]
            if request.attempts >= settings.fipe_lookup_max_attempts:
                request.status = "failed"
                request.processed_at = datetime.now(timezone.utc)
                counters["failed_final"] += 1
            else:
                request.status = "pending"
                counters["failed_temp"] += 1
            db.commit()

    return counters
