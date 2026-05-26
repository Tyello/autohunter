from __future__ import annotations

import re
import unicodedata
from collections import Counter

from sqlalchemy.orm import Session

from app.models.car_listing import CarListing
from app.models.fipe_catalog_entry import FipeCatalogEntry
from app.services.fipe_monthly_sync_service import normalize_fipe_month

_REF_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_WORD_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = {"de", "do", "da", "dos", "das", "e", "the"}


def normalize_vehicle_text(value: str | None) -> str:
    text = str(value or "").strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _tokens(value: str | None) -> set[str]:
    return {t for t in _WORD_RE.findall(normalize_vehicle_text(value)) if t and t not in _STOPWORDS}


def build_listing_fipe_query(listing) -> dict:
    return {
        "make": normalize_vehicle_text(getattr(listing, "make", None)),
        "model": normalize_vehicle_text(getattr(listing, "model", None)),
        "version": normalize_vehicle_text(getattr(listing, "version", None)),
        "year": getattr(listing, "year", None),
        "fuel_type": normalize_vehicle_text(getattr(listing, "fuel_type", None)),
        "transmission": normalize_vehicle_text(getattr(listing, "transmission", None)),
        "body_type": normalize_vehicle_text(getattr(listing, "body_type", None)),
        "doors": getattr(listing, "doors", None),
    }


def _ensure_month(db: Session, reference_month: str | None) -> str:
    if reference_month:
        return normalize_fipe_month(reference_month)
    row = db.query(FipeCatalogEntry.reference_month).order_by(FipeCatalogEntry.reference_month.desc()).first()
    if not row:
        raise ValueError("Sem dados no catálogo FIPE staging.")
    return row[0]


def find_fipe_catalog_candidates(db: Session, *, listing, reference_month: str, limit: int = 10) -> list[FipeCatalogEntry]:
    query = build_listing_fipe_query(listing)
    month = normalize_fipe_month(reference_month)
    limit = max(1, min(50, int(limit)))

    candidates_query = db.query(FipeCatalogEntry).filter(
        FipeCatalogEntry.reference_month == month,
        FipeCatalogEntry.vehicle_type == "car",
    )
    if query["make"]:
        candidates_query = candidates_query.filter(FipeCatalogEntry.brand_name.ilike(f"%{query['make']}%"))
    if query["model"]:
        candidates_query = candidates_query.filter(FipeCatalogEntry.model_name.ilike(f"%{query['model']}%"))
    if query["year"]:
        candidates_query = candidates_query.filter(FipeCatalogEntry.model_year.in_([query["year"], query["year"] - 1, query["year"] + 1]))

    rows = candidates_query.order_by(FipeCatalogEntry.model_year.desc().nullslast(), FipeCatalogEntry.model_name.asc()).limit(limit * 4).all()
    return rows[: limit * 2]


def score_fipe_candidate(*, listing_query: dict, catalog_entry) -> dict:
    score = 0
    reasons: list[str] = []
    warnings: list[str] = []

    make_tokens = _tokens(listing_query.get("make"))
    model_tokens = _tokens(listing_query.get("model"))
    version_tokens = _tokens(listing_query.get("version"))
    fuel_tokens = _tokens(listing_query.get("fuel_type"))

    brand_tokens = _tokens(getattr(catalog_entry, "brand_name", None))
    model_name_tokens = _tokens(getattr(catalog_entry, "model_name", None))
    fuel_catalog_tokens = _tokens(getattr(catalog_entry, "fuel", None))

    if make_tokens and make_tokens.intersection(brand_tokens):
        score += 25
        reasons.append("marca compatível")
    elif make_tokens:
        warnings.append("marca divergente")
        score -= 50

    if model_tokens and model_tokens.intersection(model_name_tokens):
        score += 30
        reasons.append("modelo compatível")
    elif model_tokens:
        warnings.append("modelo sem interseção relevante")
        score -= 50

    listing_year = listing_query.get("year")
    model_year = getattr(catalog_entry, "model_year", None)
    if listing_year and model_year:
        if listing_year == model_year:
            score += 25
            reasons.append("ano compatível")
        else:
            score -= 30
            warnings.append("ano divergente")

    if fuel_tokens and fuel_catalog_tokens:
        if fuel_tokens.intersection(fuel_catalog_tokens):
            score += 10
            reasons.append("combustível compatível")
        else:
            warnings.append("combustível divergente")
            score -= 5

    if version_tokens:
        common = version_tokens.intersection(model_name_tokens)
        if common:
            score += 10
            reasons.append("tokens de versão encontrados")

    score = max(0, min(100, score))
    label = "high" if score >= 80 else "medium" if score >= 60 else "low"
    return {
        "catalog_entry_id": str(catalog_entry.id),
        "fipe_code": catalog_entry.fipe_code,
        "brand_name": catalog_entry.brand_name,
        "model_name": catalog_entry.model_name,
        "model_year": catalog_entry.model_year,
        "fuel": catalog_entry.fuel,
        "price": float(catalog_entry.price) if catalog_entry.price is not None else None,
        "confidence_score": score,
        "confidence_label": label,
        "reasons": reasons,
        "warnings": warnings,
    }


def resolve_listing_to_fipe_candidates(db: Session, *, listing, reference_month: str, limit: int = 10) -> dict:
    month = normalize_fipe_month(reference_month)
    listing_id = str(getattr(listing, "id", ""))
    listing_query = build_listing_fipe_query(listing)
    if not listing_query.get("make") or not listing_query.get("model") or not listing_query.get("year"):
        return {
            "listing_id": listing_id,
            "reference_month": month,
            "query": listing_query,
            "candidates": [],
            "best_candidate": None,
            "status": "insufficient_data",
        }

    candidates = find_fipe_catalog_candidates(db, listing=listing, reference_month=month, limit=limit)
    scored = sorted((score_fipe_candidate(listing_query=listing_query, catalog_entry=row) for row in candidates), key=lambda x: x["confidence_score"], reverse=True)

    relevant = [c for c in scored if c["confidence_score"] >= 40]
    if not relevant:
        status = "no_match"
        best = None
    else:
        best = relevant[0]
        second = relevant[1] if len(relevant) > 1 else None
        if best["confidence_label"] == "high" and (second is None or (best["confidence_score"] - second["confidence_score"] >= 10)):
            status = "matched"
        elif second and (best["confidence_score"] - second["confidence_score"] < 10):
            status = "ambiguous"
        elif best["confidence_label"] in {"medium", "low"}:
            status = "ambiguous"
        else:
            status = "no_match"

    return {
        "listing_id": listing_id,
        "reference_month": month,
        "query": listing_query,
        "candidates": relevant[:limit],
        "best_candidate": best,
        "status": status,
    }


def build_fipe_resolver_coverage_report(db: Session, *, reference_month: str, limit: int = 100) -> dict:
    month = _ensure_month(db, reference_month)
    sample_limit = max(1, min(200, int(limit)))
    counters = Counter()

    listings = db.query(CarListing).order_by(CarListing.created_at.desc()).limit(sample_limit).all()
    for listing in listings:
        result = resolve_listing_to_fipe_candidates(db, listing=listing, reference_month=month, limit=5)
        counters[result["status"]] += 1
        best = result.get("best_candidate")
        if best:
            counters[f"label_{best['confidence_label']}"] += 1

    return {
        "reference_month": month,
        "sample_size": len(listings),
        "limit": sample_limit,
        "status_counts": {
            "matched": counters.get("matched", 0),
            "ambiguous": counters.get("ambiguous", 0),
            "no_match": counters.get("no_match", 0),
            "insufficient_data": counters.get("insufficient_data", 0),
        },
        "confidence_label_counts": {
            "high": counters.get("label_high", 0),
            "medium": counters.get("label_medium", 0),
            "low": counters.get("label_low", 0),
        },
    }
